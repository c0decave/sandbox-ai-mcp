// The entry point of sandbox-ai-mcp's Engram image (servers/engram/src/main.go; MIT, this repository).
//
// It is built inside Engram's module at cmd/sandbox-ai-mcp (Go lets only that module import its internal
// packages) and links nothing of Engram but internal/mcp and internal/store with what they import: no CLI,
// no HTTP API, no TUI, no Engram Cloud client, no autosync, no update check, no LLM. It serves Engram's
// "agent" tool profile over stdio with the memory in /data, and adds what the packaging needs:
//
//   - the memory is /data (store.FallbackConfig, Engram's own limits); without a writable /data the tools
//     are listed but every call answers that the folder is missing;
//   - one project per memory folder: ENGRAM_PROJECT (default "brain"), registered at the first start, so
//     reads work on a fresh folder;
//   - no tool looks at other folders: the directory/cwd arguments of mem_session_start and
//     mem_current_project are taken out of their schemas and refused (Engram would scan them and run git);
//   - every call is bounded (argument sizes, limits) and a panic in a handler becomes a tool error;
//   - stdin lines are capped (one JSON-RPC message per line).
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"os"
	"os/signal"
	"regexp"
	"sort"
	"syscall"

	engram "github.com/Gentleman-Programming/engram/v3/internal/mcp"
	"github.com/Gentleman-Programming/engram/v3/internal/store"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
)

// version is set at build time (-X main.version=...).
var version = "dev"

const (
	dataDir        = "/data"
	defaultProject = "brain"
	// The session registered at the first start of a project (startSession-PROJECT), so that it exists for reads.
	startSession = "sandbox-ai-mcp"
	// One JSON-RPC message per line: a longer line ends the server.
	maxLineBytes = 4 << 20
	// All arguments of one call, as JSON.
	maxArgumentBytes = 512 << 10
	// Long texts (Engram stores at most 50,000 bytes of a content and cuts the rest) and every other string.
	maxLongText  = 64 << 10
	maxShortText = 1 << 10
	maxLimit     = 100
	maxContext   = 50
)

// projectName is what ENGRAM_PROJECT may be: Engram's normalised form, nothing it would change.
var projectName = regexp.MustCompile(`^[a-z0-9][a-z0-9._-]{0,62}$`)

// longText are the arguments that carry a memory's text; every other string is a name, an id or a query.
var longText = map[string]bool{
	"content": true, "new_content": true, "find": true, "replace": true, "summary": true,
	"evidence": true, "reasoning": true, "observation": true,
}

// numberCaps bounds the counts Engram takes as given (mem_search_prompts and mem_review have no upper limit).
var numberCaps = map[string]float64{"limit": maxLimit, "before": maxContext, "after": maxContext}

// folderArguments are refused: they point Engram's project detection at other folders of the container.
var folderArguments = map[string][]string{
	"mem_session_start":   {"directory"},
	"mem_current_project": {"directory", "cwd"},
}

func main() {
	log.SetFlags(0)
	log.SetPrefix("engram-mcp: ")
	log.SetOutput(os.Stderr)
	if len(os.Args) > 1 {
		if os.Args[1] == "--version" {
			fmt.Println("engram", version, "(sandbox-ai-mcp)")
			return
		}
		log.Fatalf("takes no arguments (MCP over stdio; the memory is %s)", dataDir)
	}

	project := os.Getenv("ENGRAM_PROJECT")
	if project == "" {
		project = defaultProject
	}
	if normalized, _ := store.NormalizeProject(project); !projectName.MatchString(project) || normalized != project {
		log.Fatalf("ENGRAM_PROJECT %q: lower-case letters, digits, '.', '_' and '-' (no doubled - or _), at most 63",
			project)
	}

	s, unavailable := openStore(project)
	if s != nil {
		defer s.Close()
	}
	srv := newServer(s, project, unavailable)

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	stdio := server.NewStdioServer(srv)
	stdio.SetErrorLogger(log.New(os.Stderr, "engram-mcp: ", 0))
	err := stdio.Listen(ctx, &lineLimit{r: os.Stdin, max: maxLineBytes}, os.Stdout)
	if err != nil && !errors.Is(err, context.Canceled) {
		log.Print(err)
		if s != nil {
			s.Close()
		}
		os.Exit(1)
	}
}

// openStore opens the memory in /data and makes sure the project exists; without a writable /data it returns
// nil and the text every call answers with.
func openStore(project string) (*store.Store, string) {
	s, err := store.New(store.FallbackConfig(dataDir))
	if err != nil {
		log.Printf("no memory: %v", err)
		return nil, fmt.Sprintf("no memory: %s is not a writable folder; add the server with --mount %s=DIR:rw "+
			"(one folder per case)", dataDir, dataDir)
	}
	exists, err := s.ProjectExists(project)
	if err == nil && !exists {
		err = s.CreateSession(startSession+"-"+project, project, dataDir)
	}
	if err != nil {
		log.Printf("project %s: %v", project, err)
	}
	return s, ""
}

// newServer is Engram's MCP server with the "agent" tools, each behind guard.
func newServer(s *store.Store, project, unavailable string) *server.MCPServer {
	srv := engram.NewServerWithConfig(s, engram.MCPConfig{DefaultProject: project, Version: version},
		engram.ResolveTools("agent"))
	tools := srv.ListTools()
	names := make([]string, 0, len(tools))
	for name := range tools {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		tool := tools[name]
		withoutFolders(&tool.Tool, folderArguments[name])
		srv.AddTools(server.ServerTool{Tool: tool.Tool, Handler: guard(name, tool.Handler, unavailable)})
	}
	return srv
}

// withoutFolders takes the folder arguments out of a tool's input schema (Properties is copied, never shared).
func withoutFolders(tool *mcp.Tool, arguments []string) {
	if len(arguments) == 0 {
		return
	}
	properties := make(map[string]any, len(tool.InputSchema.Properties))
	for key, value := range tool.InputSchema.Properties {
		properties[key] = value
	}
	required := make([]string, 0, len(tool.InputSchema.Required))
	for _, key := range tool.InputSchema.Required {
		if !contains(arguments, key) {
			required = append(required, key)
		}
	}
	for _, key := range arguments {
		delete(properties, key)
	}
	tool.InputSchema.Properties = properties
	tool.InputSchema.Required = required
}

func contains(list []string, value string) bool {
	for _, item := range list {
		if item == value {
			return true
		}
	}
	return false
}

// guard answers for a missing /data, refuses arguments out of bounds and turns a panic into a tool error.
func guard(name string, next server.ToolHandlerFunc, unavailable string) server.ToolHandlerFunc {
	return func(ctx context.Context, req mcp.CallToolRequest) (result *mcp.CallToolResult, err error) {
		if unavailable != "" {
			return mcp.NewToolResultError(unavailable), nil
		}
		if problem := checkArguments(name, req.Params.Arguments); problem != "" {
			return mcp.NewToolResultError(name + ": " + problem), nil
		}
		defer func() {
			if r := recover(); r != nil {
				log.Printf("%s: recovered from a panic: %v", name, r)
				result, err = mcp.NewToolResultError(name+": internal error (the server's log has it)"), nil
			}
		}()
		return next(ctx, req)
	}
}

// checkArguments says what is wrong with a call's arguments, or "".
func checkArguments(name string, arguments any) string {
	if arguments == nil {
		return ""
	}
	encoded, err := json.Marshal(arguments)
	if err != nil {
		return "arguments: not JSON"
	}
	if len(encoded) > maxArgumentBytes {
		return fmt.Sprintf("arguments: more than %d KiB", maxArgumentBytes>>10)
	}
	values, ok := arguments.(map[string]any)
	if !ok {
		return "arguments: an object"
	}
	for _, key := range folderArguments[name] {
		if _, given := values[key]; given {
			return key + ": not offered here (one memory folder per server: the project is ENGRAM_PROJECT)"
		}
	}
	return checkValue("", values)
}

func checkValue(key string, value any) string {
	switch v := value.(type) {
	case string:
		limit := maxShortText
		if longText[key] {
			limit = maxLongText
		}
		if len(v) > limit {
			return fmt.Sprintf("%s: at most %d bytes", key, limit)
		}
	case float64:
		if limit, capped := numberCaps[key]; capped && (v < 0 || v > limit) {
			return fmt.Sprintf("%s: 0 to %d", key, int(limit))
		}
	case map[string]any:
		for inner, item := range v {
			if problem := checkValue(inner, item); problem != "" {
				return problem
			}
		}
	case []any:
		for _, item := range v {
			if problem := checkValue(key, item); problem != "" {
				return problem
			}
		}
	}
	return ""
}

// lineLimit passes stdin through and fails once a line grows beyond max bytes (mcp-go reads whole lines).
type lineLimit struct {
	r   io.Reader
	max int
	run int
}

var errLineTooLong = errors.New("a JSON-RPC message (one line) longer than the limit: stopped")

func (l *lineLimit) Read(p []byte) (int, error) {
	n, err := l.r.Read(p)
	for _, b := range p[:n] {
		if b == '\n' {
			l.run = 0
			continue
		}
		l.run++
		if l.run > l.max {
			return 0, errLineTooLong
		}
	}
	return n, err
}
