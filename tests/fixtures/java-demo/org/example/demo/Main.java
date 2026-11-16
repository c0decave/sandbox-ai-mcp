package org.example.demo;

/** Test input of the jadx and cfr servers (sandbox-ai-mcp): nothing here is ever run. */
public class Main {
    public static void main(String[] args) {
        Checker checker = new Checker();
        String input = args.length > 0 ? args[0] : "";
        Checker.Result result = new Checker.Result(checker.checkPassword(input));
        System.out.println(result.ok ? checker.greet() : "denied after " + checker.attempts());
    }
}
