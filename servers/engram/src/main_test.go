// Tests of sandbox-ai-mcp's entry point for Engram (run by the image build: go test ./cmd/sandbox-ai-mcp).
// They need no /data: the server is built without a store, as when /data is not mounted.
package main

import (
	"context"
	"errors"
	"io"
	"sort"
	"strings"
	"testing"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
)

// The tools of Engram's "agent" profile: tools.json of the image lists exactly these.
var agentTools = []string{
	"mem_capture_passive", "mem_compare", "mem_consolidate", "mem_context", "mem_current_project", "mem_doctor",
	"mem_get_observation", "mem_judge", "mem_judge_many", "mem_list_projects", "mem_pin", "mem_review", "mem_save",
	"mem_save_prompt", "mem_search", "mem_search_prompts", "mem_session_end", "mem_session_finalize",
	"mem_session_start", "mem_session_summary", "mem_suggest_topic_key", "mem_unpin", "mem_update",
}

func call(t *testing.T, srv *server.MCPServer, name string, arguments any) *mcp.CallToolResult {
	t.Helper()
	tool := srv.GetTool(name)
	if tool == nil {
		t.Fatalf("%s is not offered", name)
	}
	req := mcp.CallToolRequest{}
	req.Params.Name = name
	req.Params.Arguments = arguments
	result, err := tool.Handler(context.Background(), req)
	if err != nil {
		t.Fatalf("%s: %v", name, err)
	}
	return result
}

func text(result *mcp.CallToolResult) string {
	var parts []string
	for _, content := range result.Content {
		if c, ok := content.(mcp.TextContent); ok {
			parts = append(parts, c.Text)
		}
	}
	return strings.Join(parts, "\n")
}

func TestTheAgentToolsAndNoOthers(t *testing.T) {
	srv := newServer(nil, "brain", "no memory")
	var names []string
	for name := range srv.ListTools() {
		names = append(names, name)
	}
	sort.Strings(names)
	if strings.Join(names, ",") != strings.Join(agentTools, ",") {
		t.Fatalf("tools %v, want %v", names, agentTools)
	}
}

func TestWithoutDataEveryCallSaysSo(t *testing.T) {
	srv := newServer(nil, "brain", "no memory: /data is not a writable folder")
	for _, name := range agentTools {
		result := call(t, srv, name, map[string]any{})
		if !result.IsError || !strings.Contains(text(result), "/data is not a writable folder") {
			t.Fatalf("%s without /data: %+v", name, result)
		}
	}
}

func TestNoToolTakesAFolder(t *testing.T) {
	srv := newServer(nil, "brain", "")
	for name, arguments := range folderArguments {
		tool := srv.GetTool(name)
		for _, key := range arguments {
			if _, ok := tool.Tool.InputSchema.Properties[key]; ok {
				t.Fatalf("%s still offers %s", name, key)
			}
			for _, required := range tool.Tool.InputSchema.Required {
				if required == key {
					t.Fatalf("%s still requires %s", name, key)
				}
			}
			result := call(t, srv, name, map[string]any{key: "/etc"})
			if !result.IsError || !strings.Contains(text(result), key+": not offered here") {
				t.Fatalf("%s with %s: %+v", name, key, result)
			}
		}
	}
	if _, ok := srv.GetTool("mem_session_start").Tool.InputSchema.Properties["id"]; !ok {
		t.Fatal("mem_session_start lost its id argument")
	}
}

func TestArgumentBounds(t *testing.T) {
	cases := []struct {
		arguments any
		problem   string
	}{
		{map[string]any{"title": strings.Repeat("x", maxShortText+1)}, "title: at most 1024 bytes"},
		{map[string]any{"query": strings.Repeat("x", maxShortText+1)}, "query: at most 1024 bytes"},
		{map[string]any{"content": strings.Repeat("x", maxLongText+1)}, "content: at most 65536 bytes"},
		{map[string]any{"limit": float64(101)}, "limit: 0 to 100"},
		{map[string]any{"limit": float64(-1)}, "limit: 0 to 100"},
		{map[string]any{"before": float64(51)}, "before: 0 to 50"},
		{map[string]any{"judgments": []any{map[string]any{"judgment_id": strings.Repeat("j", 2000)}}},
			"judgment_id: at most 1024 bytes"},
		{map[string]any{"judgments": manyEvidences(10, 60000)}, "arguments: more than 512 KiB"},
		{[]any{"x"}, "arguments: an object"},
	}
	for _, c := range cases {
		if got := checkArguments("mem_save", c.arguments); got != c.problem {
			t.Errorf("%.80v: %q, want %q", c.arguments, got, c.problem)
		}
	}
	for _, ok := range []any{nil, map[string]any{"title": "a", "content": strings.Repeat("x", 50000), "limit": float64(100)}} {
		if got := checkArguments("mem_save", ok); got != "" {
			t.Errorf("%.80v refused: %s", ok, got)
		}
	}
}

func manyEvidences(n, size int) []any {
	items := make([]any, n)
	for i := range items {
		items[i] = map[string]any{"evidence": strings.Repeat("e", size)}
	}
	return items
}

func TestAPanicIsAToolError(t *testing.T) {
	handler := guard("mem_x", func(context.Context, mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		var m map[string]int
		m["x"] = 1
		return nil, nil
	}, "")
	result, err := handler(context.Background(), mcp.CallToolRequest{})
	if err != nil || result == nil || !result.IsError || !strings.Contains(text(result), "internal error") {
		t.Fatalf("%+v %v", result, err)
	}
}

func TestLongLinesStopTheServer(t *testing.T) {
	short := strings.Repeat("a", 10) + "\n" + strings.Repeat("b", 10) + "\n"
	data, err := io.ReadAll(&lineLimit{r: strings.NewReader(short), max: 10})
	if err != nil || string(data) != short {
		t.Fatalf("%q %v", data, err)
	}
	_, err = io.ReadAll(&lineLimit{r: strings.NewReader(strings.Repeat("a", 11)), max: 10})
	if !errors.Is(err, errLineTooLong) {
		t.Fatalf("an 11-byte line with a 10-byte limit: %v", err)
	}
}

func TestProjectNames(t *testing.T) {
	for _, name := range []string{"brain", "case-2026.11", "a_b"} {
		if !projectName.MatchString(name) {
			t.Errorf("%s refused", name)
		}
	}
	for _, name := range []string{"", "Brain", "../x", "a/b", "-x", strings.Repeat("a", 64), "a b"} {
		if projectName.MatchString(name) {
			t.Errorf("%q taken", name)
		}
	}
}
