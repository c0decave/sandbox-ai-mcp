package org.example.demo;

/** Test input of the jadx and cfr servers (sandbox-ai-mcp): nothing here is ever run. */
public class Checker {
    public static final String MARKER = "MCPHUB-TEST-MARKER";
    private int attempts;

    public boolean checkPassword(String candidate) {
        attempts++;
        return "hunter2".equals(candidate);
    }

    public String greet() {
        return greet("world");
    }

    public String greet(String name) {
        return "Hello, " + name + "!";
    }

    public int attempts() {
        return attempts;
    }

    public static class Result {
        public final boolean ok;

        public Result(boolean ok) {
            this.ok = ok;
        }
    }
}
