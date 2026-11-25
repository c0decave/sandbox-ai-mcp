// Tests of servers/gitea/src/main.go (MIT, this repository), run by the image's build (go test): gitea-mcp's tools
// behind the guard, against a fake Gitea (httptest) that records every request.
package main

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"sync"
	"testing"
	"unicode/utf8"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

// fakeGitea answers every request with a small JSON document of the shape gitea-mcp expects there and records the
// method and path of each.
type fakeGitea struct {
	mu       sync.Mutex
	requests []string
	big      string
}

func (f *fakeGitea) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	f.requests = append(f.requests, r.Method+" "+r.URL.Path)
	f.mu.Unlock()
	_, _ = io.Copy(io.Discard, r.Body)
	w.Header().Set("Content-Type", "application/json")
	path := r.URL.Path
	switch {
	case path == "/api/v1/version":
		_, _ = io.WriteString(w, `{"version":"1.25.0"}`)
	case strings.HasPrefix(path, "/api/v1/repos/o/r/contents/big.txt"):
		doc, _ := json.Marshal(map[string]any{"type": "file", "name": "big.txt", "path": "big.txt",
			"encoding": "base64", "content": f.big, "size": 100000, "sha": "0123"})
		_, _ = w.Write(doc)
	case strings.HasSuffix(path, "/logs"):
		w.Header().Set("Content-Type", "text/plain")
		_, _ = io.WriteString(w, "2026-11-25T10:00:00Z line one\n2026-11-25T10:00:01Z ::error::FAIL two\n")
	case path == "/api/v1/user":
		_, _ = io.WriteString(w, `{"id":1,"login":"me","full_name":"Me"}`)
	default:
		// a list where gitea-mcp expects one, an object elsewhere: decoding errors are tool errors, which is fine
		// here - every request is recorded either way
		if strings.HasSuffix(path, "s") || strings.Contains(path, "/search") {
			_, _ = io.WriteString(w, `[]`)
		} else {
			_, _ = io.WriteString(w, `{}`)
		}
	}
}

func (f *fakeGitea) seen() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return slices.Clone(f.requests)
}

func env(values map[string]string) func(string) string {
	return func(name string) string { return values[name] }
}

// connect starts the server configured by VALUES and returns a client session to it.
func connect(t *testing.T, values map[string]string) (*mcp.ClientSession, config) {
	t.Helper()
	cfg := configure(env(values))
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	server := newServer(cfg, logger)
	clientTransport, serverTransport := mcp.NewInMemoryTransports()
	ctx := context.Background()
	if _, err := server.Connect(ctx, serverTransport, nil); err != nil {
		t.Fatal(err)
	}
	session, err := mcp.NewClient(&mcp.Implementation{Name: "test", Version: "1"}, nil).Connect(ctx, clientTransport, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = session.Close() })
	return session, cfg
}

func call(t *testing.T, session *mcp.ClientSession, name string, arguments map[string]any) (string, bool) {
	t.Helper()
	result, err := session.CallTool(context.Background(), &mcp.CallToolParams{Name: name, Arguments: arguments})
	if err != nil {
		t.Fatalf("%s: %v", name, err)
	}
	var text strings.Builder
	for _, item := range result.Content {
		c, ok := item.(*mcp.TextContent)
		if !ok {
			t.Fatalf("%s: a %T in the answer", name, item)
		}
		text.WriteString(c.Text)
	}
	if result.StructuredContent != nil {
		t.Fatalf("%s: structuredContent in the answer", name)
	}
	return text.String(), result.IsError
}

func toolNames(t *testing.T, session *mcp.ClientSession) map[string]*mcp.Tool {
	t.Helper()
	list, err := session.ListTools(context.Background(), &mcp.ListToolsParams{})
	if err != nil {
		t.Fatal(err)
	}
	out := map[string]*mcp.Tool{}
	for _, tool := range list.Tools {
		out[tool.Name] = tool
	}
	return out
}

func properties(t *testing.T, tool *mcp.Tool) map[string]any {
	t.Helper()
	raw, err := json.Marshal(tool.InputSchema)
	if err != nil {
		t.Fatal(err)
	}
	var schema struct {
		Properties map[string]any `json:"properties"`
	}
	if err := json.Unmarshal(raw, &schema); err != nil {
		t.Fatal(err)
	}
	return schema.Properties
}

func methods(t *testing.T, tool *mcp.Tool) []string {
	method, _ := properties(t, tool)["method"].(map[string]any)
	var out []string
	values, _ := method["enum"].([]any)
	for _, v := range values {
		out = append(out, v.(string))
	}
	return out
}

// The 28 read tools of gitea-mcp v1.13.0 (tools.json beside this server).
var readTools = []string{"actions_config_read", "actions_run_read", "branch_read", "commit_read", "get_dir_contents",
	"get_file_contents", "get_gitea_mcp_server_version", "get_me", "get_repository_tree", "get_user_orgs",
	"issue_read", "label_read", "list_issues", "list_pull_requests", "milestone_read", "notification_read",
	"package_read", "project_read", "pull_request_read", "release_read", "repo_read", "search_issues",
	"search_org_teams", "search_repos", "search_users", "tag_read", "timetracking_read", "wiki_read"}

func TestReadOnlyByDefault(t *testing.T) {
	session, _ := connect(t, map[string]string{"GITEA_HOST": "https://gitea.example.org"})
	tools := toolNames(t, session)
	names := slices.Sorted(func(yield func(string) bool) {
		for name := range tools {
			if !yield(name) {
				return
			}
		}
	})
	if !slices.Equal(names, readTools) {
		t.Fatalf("tools: %v", names)
	}
	for name, tool := range tools {
		if _, ok := properties(t, tool)["output_path"]; ok {
			t.Errorf("%s offers output_path", name)
		}
		for _, method := range methods(t, tool) {
			if strings.HasPrefix(method, "download_") {
				t.Errorf("%s offers %s", name, method)
			}
		}
		if tool.Annotations == nil || !tool.Annotations.ReadOnlyHint {
			t.Errorf("%s is not marked read-only", name)
		}
	}
	// the listing is a copy: gitea-mcp's own schema keeps its methods for the next listing
	again := toolNames(t, session)
	if got := methods(t, again["actions_run_read"]); slices.Contains(got, "download_job_log") ||
		!slices.Contains(got, "get_job_log_preview") {
		t.Fatalf("second listing: %v", got)
	}
}

func TestWritesOnlyWithGiteaWrite(t *testing.T) {
	session, _ := connect(t, map[string]string{"GITEA_HOST": "https://gitea.example.org", "GITEA_WRITE": "1"})
	tools := toolNames(t, session)
	for _, name := range []string{"issue_write", "pull_request_write", "create_or_update_file", "repo_write"} {
		if tools[name] == nil {
			t.Errorf("%s is missing with GITEA_WRITE=1", name)
		}
	}
	if len(tools) <= len(readTools) {
		t.Fatalf("%d tools with GITEA_WRITE=1", len(tools))
	}
	for _, value := range []string{"true", "yes", "0", ""} {
		session, _ := connect(t, map[string]string{"GITEA_HOST": "https://gitea.example.org", "GITEA_WRITE": value})
		if tools := toolNames(t, session); tools["issue_write"] != nil {
			t.Errorf("GITEA_WRITE=%q lists the write tools", value)
		}
	}
}

func TestScopesAndToolsCutTheList(t *testing.T) {
	session, _ := connect(t, map[string]string{"GITEA_HOST": "https://g.example", "GITEA_SCOPES": "Issue, pull-request"})
	tools := toolNames(t, session)
	if tools["issue_read"] == nil || tools["pull_request_read"] == nil || tools["repo_read"] != nil {
		t.Fatalf("GITEA_SCOPES: %v", tools)
	}
	session, _ = connect(t, map[string]string{"GITEA_HOST": "https://g.example", "GITEA_TOOLS": "get_me,get_file_contents"})
	if tools := toolNames(t, session); len(tools) != 2 {
		t.Fatalf("GITEA_TOOLS: %v", tools)
	}
}

func TestEveryReadMethodOnlyReadsTheGiteaHost(t *testing.T) {
	fake := &fakeGitea{}
	server := httptest.NewServer(fake)
	defer server.Close()
	session, _ := connect(t, map[string]string{"GITEA_HOST": server.URL + "/", "GITEA_ACCESS_TOKEN": "t0ken"})
	arguments := map[string]any{"owner": "o", "repo": "r", "org": "g", "username": "u", "index": 1,
		"issue_number": 1, "pull_number": 1, "id": 1, "run_id": 1, "job_id": 1, "artifact_id": 1, "comment_id": 1,
		"attachment_id": 1, "review_id": 1, "release_id": 1, "project_id": 1, "column_id": 1, "workflow_id": "ci.yml",
		"name": "n", "tag": "v1", "tag_name": "v1", "branch": "main", "ref": "main", "sha": "0123", "path": "README.md",
		"page_name": "Home", "query": "q", "keyword": "k", "type": "generic", "version": "1", "base": "main",
		"head": "dev", "basehead": "main...dev", "commit_sha": "0123", "since": "2026-11-01T00:00:00Z"}
	calls := 0
	for _, name := range readTools {
		tool := toolNames(t, session)[name]
		list := methods(t, tool)
		if len(list) == 0 {
			list = []string{""}
		}
		for _, method := range list {
			args := map[string]any{}
			for key, value := range arguments {
				args[key] = value
			}
			if method != "" {
				args["method"] = method
			}
			text, _ := call(t, session, name, args)
			calls++
			if n := utf8.RuneCountInString(text); n > maxAnswer+300 {
				t.Errorf("%s %s: %d characters", name, method, n)
			}
			if strings.Contains(text, "t0ken") {
				t.Errorf("%s %s: the answer has the token", name, method)
			}
		}
	}
	requests := fake.seen()
	if calls < 60 || len(requests) < 40 {
		t.Fatalf("%d calls, %d requests", calls, len(requests))
	}
	for _, request := range requests {
		method, path, _ := strings.Cut(request, " ")
		if method != http.MethodGet {
			t.Errorf("read-only sent %s", request)
		}
		if !strings.HasPrefix(path, "/api/v1/") && !strings.HasPrefix(path, "/attachments/") {
			t.Errorf("outside the API: %s", request)
		}
	}
}

func TestLongAnswersAreCut(t *testing.T) {
	fake := &fakeGitea{big: strings.Repeat("YWJjZGVm", 12500)} // base64 of "abcdef" x 12,500: 75,000 characters
	server := httptest.NewServer(fake)
	defer server.Close()
	session, _ := connect(t, map[string]string{"GITEA_HOST": server.URL})
	text, isError := call(t, session, "get_file_contents", map[string]any{"owner": "o", "repo": "r", "path": "big.txt"})
	if isError {
		t.Fatalf("error: %s", text)
	}
	if n := utf8.RuneCountInString(text); n > maxAnswer+300 || !strings.Contains(text, "[cut: the answer has") {
		t.Fatalf("%d characters: %s", n, text[len(text)-200:])
	}
	text, _ = call(t, session, "actions_run_read", map[string]any{"method": "get_job_log_preview", "owner": "o",
		"repo": "r", "job_id": 7, "pattern": "::error::", "context_lines": 0})
	if !strings.Contains(text, "FAIL two") || strings.Contains(text, "line one") {
		t.Fatalf("log preview: %s", text)
	}
}

func TestRefusedCalls(t *testing.T) {
	fake := &fakeGitea{}
	server := httptest.NewServer(fake)
	defer server.Close()
	session, _ := connect(t, map[string]string{"GITEA_HOST": server.URL, "GITEA_WRITE": "1"})
	for _, c := range []struct {
		tool string
		args map[string]any
		want string
	}{
		{"actions_run_read", map[string]any{"method": "download_job_log", "owner": "o", "repo": "r", "job_id": 1},
			"is not offered"},
		{"actions_run_read", map[string]any{"method": "download_artifact", "owner": "o", "repo": "r", "artifact_id": 1},
			"is not offered"},
		{"issue_read", map[string]any{"method": "download_attachment", "owner": "o", "repo": "r", "attachment_uuid": "x"},
			"is not offered"},
		{"release_read", map[string]any{"method": "download_asset", "owner": "o", "repo": "r", "id": 1},
			"is not offered"},
		{"issue_read", map[string]any{"method": "get", "owner": "o", "repo": "r", "issue_number": 1,
			"output_path": "/tmp/x"}, "output_path is not offered"},
		{"repo_read", map[string]any{"method": "get", "owner": "..", "repo": "admin"}, "is not a name"},
		{"repo_read", map[string]any{"method": "get", "owner": "o", "repo": "a/b"}, "is not a name"},
		{"actions_config_read", map[string]any{"method": "get_repo_variable", "owner": "o", "repo": "r",
			"name": ".."}, "is not a name"},
		{"issue_write", map[string]any{"method": "create", "owner": "o", "repo": "r", "title": "t",
			"body": strings.Repeat("x", maxArgumentBytes)}, "bytes; at most"},
	} {
		text, isError := call(t, session, c.tool, c.args)
		if !isError || !strings.Contains(text, c.want) {
			t.Errorf("%s %v: %v %s", c.tool, c.args["method"], isError, text)
		}
	}
	if requests := fake.seen(); len(requests) != 0 {
		t.Fatalf("a refused call reached Gitea: %v", requests)
	}
	// a label, branch or tag name may hold a slash (kind/bug, feature/x)
	text, _ := call(t, session, "branch_read", map[string]any{"method": "get", "owner": "o", "repo": "r",
		"branch": "feature/x"})
	if strings.Contains(text, "is not a name") {
		t.Fatalf("branch with a slash: %s", text)
	}
}

func TestTheHostIsChecked(t *testing.T) {
	for raw, want := range map[string]string{
		"":                             "GITEA_HOST is not set",
		"gitea.example.org":            "is not an address",
		"ftp://gitea.example.org":      "is not an address",
		"https://me:pw@gitea.example":  "is not an address",
		"https://gitea.example/?x=1":   "is not an address",
		"https://gitea.example/#frag":  "is not an address",
		"https://gitea.example\n/evil": "is not an address",
	} {
		session, cfg := connect(t, map[string]string{"GITEA_HOST": raw})
		if !strings.Contains(cfg.problem, want) {
			t.Errorf("%q: %q", raw, cfg.problem)
		}
		if tools := toolNames(t, session); len(tools) != len(readTools) {
			t.Errorf("%q: the tools are listed without a host too: %d", raw, len(tools))
		}
		text, isError := call(t, session, "get_me", nil)
		if !isError || !strings.Contains(text, want) {
			t.Errorf("%q: %s", raw, text)
		}
	}
	for raw, want := range map[string]string{
		"https://gitea.example.org/":      "https://gitea.example.org",
		"http://192.168.1.20:3000":        "http://192.168.1.20:3000",
		"https://example.org/gitea/":      "https://example.org/gitea",
		" https://gitea.example.org:8443": "https://gitea.example.org:8443",
	} {
		if got, problem := checkedHost(raw); got != want || problem != "" {
			t.Errorf("%q: %q %q", raw, got, problem)
		}
	}
	if cfg := configure(env(map[string]string{"GITEA_HOST": "https://g.example", "GITEA_ACCESS_TOKEN": "a\nb"})); cfg.problem == "" {
		t.Fatal("a token with a newline is taken")
	}
}

func TestBound(t *testing.T) {
	answer := &mcp.CallToolResult{
		Content: []mcp.Content{&mcp.TextContent{Text: strings.Repeat("ä", maxAnswer-10)},
			&mcp.ImageContent{Data: []byte("png"), MIMEType: "image/png"}, &mcp.TextContent{Text: "tail"}},
		StructuredContent: map[string]any{"a": 1},
	}
	bound(answer)
	var text strings.Builder
	for _, item := range answer.Content {
		text.WriteString(item.(*mcp.TextContent).Text)
	}
	if answer.StructuredContent != nil || !utf8.ValidString(text.String()) || !strings.Contains(text.String(), "[cut:") {
		t.Fatalf("%q", text.String()[maxAnswer-40:])
	}
	if n := utf8.RuneCountInString(text.String()); n > maxAnswer+300 {
		t.Fatalf("%d characters", n)
	}
}
