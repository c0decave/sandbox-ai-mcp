// GhidraBridge: the part of the ghidra MCP server (sandbox-ai-mcp) that runs in the JVM. It imports ONE input file with
// Ghidra's own headless API (ProgramLoader, AutoAnalysisManager, DecompInterface - no project, no script, no
// GhidraScript bundle, no Ghidra Server), analyses it once and answers the Python server (src/server.py) over
// stdin/stdout, one JSON object per line:
//   request  {"id": N, "op": "...", ...}
//   answer   {"id": N, "ok": true, "result": {...}}  or  {"id": N, "ok": false, "error": "..."}
// The first line it writes is the answer to the import and analysis (id 0). It reads only the file it is given (a link
// the Python server made to the descriptor of the file it opened and checked) and Ghidra's own installation; Ghidra
// writes its temporary program database, its settings and its log below java.io.tmpdir and user.home (both a scratch
// folder of the Python server below /tmp). Nothing is saved: the program is never written to a project. System.out
// is pointed at stderr before Ghidra is touched, so nothing but answers reaches the protocol stream.
//
//   java -Djava.system.class.loader=ghidra.GhidraClassLoader ... -cp Utility.jar:BRIDGE_DIR ghidra.Ghidra GhidraBridge
//        INPUT NAME ANALYSIS_SECONDS [LANGUAGE [COMPILER]]
import java.io.BufferedReader;
import java.io.File;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.concurrent.TimeUnit;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import ghidra.GhidraApplicationLayout;
import ghidra.GhidraLaunchable;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.plugin.core.analysis.AutoAnalysisManager;
import ghidra.app.util.bin.ByteProvider;
import ghidra.app.util.bin.FileByteProvider;
import ghidra.app.util.importer.MessageLog;
import ghidra.app.util.importer.ProgramLoader;
import ghidra.app.util.opinion.LoadException;
import ghidra.app.util.opinion.LoadResults;
import ghidra.formats.gfilesystem.FSRL;
import ghidra.formats.gfilesystem.FileSystemService;
import ghidra.framework.Application;
import ghidra.framework.HeadlessGhidraApplicationConfiguration;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSetView;
import ghidra.program.model.data.StringDataInstance;
import ghidra.program.model.lang.CompilerSpecDescription;
import ghidra.program.model.lang.LanguageDescription;
import ghidra.program.model.lang.LanguageService;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.listing.Program;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.ExternalLocation;
import ghidra.program.model.symbol.ExternalManager;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolIterator;
import ghidra.program.model.symbol.SymbolTable;
import ghidra.program.model.symbol.SymbolType;
import ghidra.program.util.DefaultLanguageService;
import ghidra.program.util.DefinedStringIterator;
import ghidra.program.util.GhidraProgramUtilities;
import ghidra.util.task.TaskMonitor;
import ghidra.util.task.TimeoutTaskMonitor;

public final class GhidraBridge implements GhidraLaunchable {
	/** Seconds the decompiler may take for one function. */
	static final int DECOMPILE_SECONDS = 30;
	/** Characters of a string shown (the Python server cuts lines again). */
	static final int MAX_STRING_CHARS = 300;
	/** Instructions of one disassembly at most (the Python server pages what it shows). */
	static final int MAX_INSTRUCTIONS = 20_000;
	/** References and calls listed at most. */
	static final int MAX_REFS = 2_000;
	/** Functions with the same name given back at most. */
	static final int MAX_MATCHES = 20;

	Program program;
	DecompInterface decompiler;
	String analysisNote = "";
	long analysisMillis;

	// --- the import and the analysis ---------------------------------------------------------------------------------

	Map<String, Object> load(File input, String name, int analysisSeconds, String language, String compiler)
			throws Exception {
		MessageLog log = new MessageLog();
		FSRL fsrl = FileSystemService.getInstance().getLocalFSRL(input);
		try (ByteProvider bytes = new FileByteProvider(input, fsrl, java.nio.file.AccessMode.READ)) {
			ProgramLoader.Builder builder = ProgramLoader.builder()
					.source(bytes)
					.name(name)
					.log(log)
					.monitor(TaskMonitor.DUMMY);
			if (!language.isEmpty()) {
				known(language);
				builder.language(language);
				if (!compiler.isEmpty()) {
					builder.compiler(compiler);
				}
			}
			LoadResults<Program> results;
			try {
				results = builder.load();
			} catch (LoadException e) {
				if (language.isEmpty() && String.valueOf(e.getMessage()).contains("No load spec found")) {
					throw new Refusal("Ghidra does not recognise the format (raw firmware or a blob?): open it "
							+ "with its processor as language, e.g. ARM:LE:32:v8, ARM:LE:32:Cortex, AARCH64:LE:64:v8A, "
							+ "MIPS:BE:32:default, x86:LE:32:default, PowerPC:BE:32:default, 8051:BE:16:default");
				}
				throw e;
			}
			// Only the primary program: libraries are not loaded from disk (Ghidra's default) and others are dropped.
			program = results.getPrimaryDomainObject(this);
			results.close();
		}
		long start = System.nanoTime();
		TimeoutTaskMonitor monitor = TimeoutTaskMonitor.timeoutIn(analysisSeconds, TimeUnit.SECONDS);
		int tx = program.startTransaction("analysis");
		try {
			AutoAnalysisManager manager = AutoAnalysisManager.getAnalysisManager(program);
			manager.initializeOptions();
			manager.reAnalyzeAll(null);
			manager.startAnalysis(monitor, false);
			GhidraProgramUtilities.markProgramAnalyzed(program);
		} finally {
			program.endTransaction(tx, true);
		}
		analysisMillis = (System.nanoTime() - start) / 1_000_000;
		if (monitor.didTimeout()) {
			analysisNote = "the analysis was stopped after " + analysisSeconds
					+ " s (GHIDRA_ANALYSIS_SECONDS): functions, references and names may be incomplete";
		}
		decompiler = new DecompInterface();
		DecompileOptions options = new DecompileOptions();
		options.grabFromProgram(program);
		decompiler.setOptions(options);
		decompiler.toggleCCode(true);
		decompiler.toggleSyntaxTree(false);
		decompiler.setSimplificationStyle("decompile");
		if (!decompiler.openProgram(program)) {
			throw new Refusal("the decompiler did not start: " + decompiler.getLastMessage());
		}
		return info();
	}

	/** LANGUAGE is one Ghidra has; else a refusal naming those of the same processor (or every processor). */
	static void known(String language) {
		LanguageService service = DefaultLanguageService.getLanguageService();
		String processor = language.split(":")[0];
		TreeSet<String> same = new TreeSet<>();
		TreeSet<String> processors = new TreeSet<>();
		for (LanguageDescription d : service.getLanguageDescriptions(false)) {
			String id = d.getLanguageID().getIdAsString();
			if (id.equals(language)) {
				return;
			}
			processors.add(d.getProcessor().toString());
			if (d.getProcessor().toString().equalsIgnoreCase(processor)) {
				same.add(id + " (compilers: " + String.join(", ", compilers(d)) + ")");
			}
		}
		throw new Refusal("Ghidra has no language " + language + (same.isEmpty()
				? "; its processors: " + String.join(", ", processors)
				: "; those of " + processor + ": " + String.join("; ", same)));
	}

	static List<String> compilers(LanguageDescription d) {
		List<String> out = new ArrayList<>();
		for (CompilerSpecDescription c : d.getCompatibleCompilerSpecDescriptions()) {
			out.add(c.getCompilerSpecID().getIdAsString());
		}
		return out;
	}

	Map<String, Object> info() {
		Map<String, Object> out = new LinkedHashMap<>();
		out.put("ghidra", Application.getApplicationVersion());
		out.put("format", program.getExecutableFormat());
		out.put("language", program.getLanguageID().getIdAsString());
		out.put("processor", program.getLanguage().getProcessor().toString());
		out.put("endian", program.getLanguage().isBigEndian() ? "big" : "little");
		out.put("pointer_bits", program.getDefaultPointerSize() * 8);
		out.put("compiler", program.getCompilerSpec().getCompilerSpecID().getIdAsString());
		out.put("image_base", program.getImageBase().toString());
		out.put("sha256", program.getExecutableSHA256());
		int functions = 0;
		int thunks = 0;
		for (Function f : program.getFunctionManager().getFunctions(true)) {
			functions++;
			if (f.isThunk()) {
				thunks++;
			}
		}
		out.put("functions", functions);
		out.put("thunks", thunks);
		out.put("imports", program.getFunctionManager().getExternalFunctions().hasNext() ? countImports() : 0);
		int exports = 0;
		for (Iterator<Address> it = program.getSymbolTable().getExternalEntryPointIterator(); it.hasNext(); it.next()) {
			exports++;
		}
		out.put("entry_points", exports);
		int strings = 0;
		for (Iterator<Data> it = DefinedStringIterator.forProgram(program); it.hasNext(); it.next()) {
			strings++;
		}
		out.put("strings", strings);
		List<Map<String, Object>> blocks = new ArrayList<>();
		for (MemoryBlock block : program.getMemory().getBlocks()) {
			Map<String, Object> b = new LinkedHashMap<>();
			b.put("name", block.getName());
			b.put("start", block.getStart().toString());
			b.put("end", block.getEnd().toString());
			b.put("size", block.getSize());
			b.put("perms", (block.isRead() ? "r" : "-") + (block.isWrite() ? "w" : "-") + (block.isExecute() ? "x" : "-"));
			b.put("initialized", block.isInitialized());
			blocks.add(b);
		}
		out.put("blocks", blocks);
		// The entry points that are functions, the program's start ("entry", "_start", "main", ...) first.
		List<Function> entryFunctions = new ArrayList<>();
		for (Iterator<Address> it = program.getSymbolTable().getExternalEntryPointIterator(); it.hasNext();) {
			Function f = program.getFunctionManager().getFunctionAt(it.next());
			if (f != null && !f.isThunk()) {
				entryFunctions.add(f);
			}
		}
		List<String> first = List.of("entry", "_start", "start", "main", "WinMain", "wWinMain", "DllMain");
		entryFunctions.sort(Comparator.comparing((Function f) -> first.contains(f.getName())
				? first.indexOf(f.getName()) : first.size()).thenComparing(Function::getEntryPoint));
		List<String> entries = new ArrayList<>();
		for (Function f : entryFunctions.subList(0, Math.min(8, entryFunctions.size()))) {
			entries.add(f.getEntryPoint() + " " + f.getName(true));
		}
		out.put("entries", entries);
		out.put("analysis_ms", analysisMillis);
		out.put("analysis_note", analysisNote);
		return out;
	}

	int countImports() {
		int n = 0;
		for (SymbolIterator it = program.getSymbolTable().getExternalSymbols(); it.hasNext(); it.next()) {
			n++;
		}
		return n;
	}

	// --- arguments ---------------------------------------------------------------------------------------------------

	static String str(JsonObject req, String key) {
		return req.has(key) && !req.get(key).isJsonNull() ? req.get(key).getAsString() : "";
	}

	static int num(JsonObject req, String key, int fallback) {
		return req.has(key) && !req.get(key).isJsonNull() ? req.get(key).getAsInt() : fallback;
	}

	/** An address the program has: "0x401000", "401000" or with its space ("ram:00401000"); null when it is none. */
	Address address(String text) {
		String t = text.trim();
		if (t.isEmpty() || t.length() > 64) {
			return null;
		}
		String plain = t.startsWith("0x") || t.startsWith("0X") ? t.substring(2) : t;
		Address a = null;
		if (plain.matches("[0-9a-fA-F]{1,16}")) {
			try {
				a = program.getAddressFactory().getDefaultAddressSpace().getAddress(plain);
			} catch (Exception e) {
				a = null;
			}
		} else if (t.matches("[A-Za-z_][A-Za-z0-9_]{0,31}:[0-9a-fA-F]{1,16}")) {
			a = program.getAddressFactory().getAddress(t);
		}
		return a != null && program.getMemory().contains(a) ? a : null;
	}

	/** The functions NAME or ADDRESS means: the one containing an address, else those of that name (any namespace). */
	List<Function> functions(String spec) {
		List<Function> found = new ArrayList<>();
		Address a = address(spec);
		if (a != null) {
			Function f = program.getFunctionManager().getFunctionContaining(a);
			if (f != null) {
				found.add(f);
			}
			return found;
		}
		String wanted = spec.trim();
		for (Function f : program.getFunctionManager().getFunctions(true)) {
			if (f.getName().equals(wanted) || f.getName(true).equals(wanted)) {
				found.add(f);
				if (found.size() >= MAX_MATCHES) {
					break;
				}
			}
		}
		return found;
	}

	Function function(JsonObject req) {
		String spec = str(req, "function");
		List<Function> found = functions(spec);
		if (found.isEmpty()) {
			Address a = address(spec);
			if (a != null) {
				throw new Refusal("no function contains " + a + " (list_functions shows the functions)");
			}
			throw new Refusal("no function " + spec + similar(spec));
		}
		if (found.size() > 1) {
			List<String> where = new ArrayList<>();
			for (Function f : found) {
				where.add(f.getEntryPoint() + " " + f.getName(true));
			}
			throw new Refusal(found.size() + " functions are named " + spec + ": name one by its address: "
					+ String.join(", ", where));
		}
		return found.get(0);
	}

	String similar(String spec) {
		String needle = spec.toLowerCase(Locale.ROOT);
		List<String> close = new ArrayList<>();
		for (Function f : program.getFunctionManager().getFunctions(true)) {
			if (f.getName().toLowerCase(Locale.ROOT).contains(needle)) {
				close.add(f.getName(true) + " (" + f.getEntryPoint() + ")");
				if (close.size() >= 8) {
					break;
				}
			}
		}
		return close.isEmpty() ? " (list_functions shows the functions)" : "; similar: " + String.join(", ", close);
	}

	static Map<String, Object> page(List<?> items, int total, int offset) {
		Map<String, Object> out = new LinkedHashMap<>();
		out.put("total", total);
		out.put("offset", offset);
		out.put("items", items);
		return out;
	}

	static boolean matches(String text, String needle) {
		return needle.isEmpty() || text.toLowerCase(Locale.ROOT).contains(needle);
	}

	// --- the operations ----------------------------------------------------------------------------------------------

	Object listFunctions(JsonObject req) {
		String needle = str(req, "filter").toLowerCase(Locale.ROOT);
		int offset = num(req, "offset", 0);
		int max = num(req, "max", 200);
		boolean thunks = req.has("thunks") && req.get("thunks").getAsBoolean();
		List<Object> items = new ArrayList<>();
		int total = 0;
		for (Function f : program.getFunctionManager().getFunctions(true)) {
			if ((!thunks && f.isThunk()) || !matches(f.getName(true), needle)) {
				continue;
			}
			if (total >= offset && items.size() < max) {
				items.add(new Object[] { f.getEntryPoint().toString(), f.getName(true), f.getBody().getNumAddresses(),
						f.isThunk() });
			}
			total++;
		}
		return page(items, total, offset);
	}

	Object decompile(JsonObject req) {
		Function f = function(req);
		DecompileResults results = decompiler.decompileFunction(f, DECOMPILE_SECONDS, TaskMonitor.DUMMY);
		Map<String, Object> out = new LinkedHashMap<>();
		out.put("function", f.getName(true));
		out.put("entry", f.getEntryPoint().toString());
		out.put("signature", f.getPrototypeString(false, false));
		if (results == null || !results.decompileCompleted() || results.getDecompiledFunction() == null) {
			String why = results == null ? "no result" : results.isTimedOut() ? "it took longer than "
					+ DECOMPILE_SECONDS + " s" : results.getErrorMessage();
			throw new Refusal("the decompiler failed on " + f.getName(true) + " at " + f.getEntryPoint() + ": "
					+ (why == null || why.isBlank() ? "no reason given" : why.trim())
					+ " (disassemble_function shows its instructions)");
		}
		out.put("code", results.getDecompiledFunction().getC());
		return out;
	}

	Object disassemble(JsonObject req) {
		Function f = function(req);
		Listing listing = program.getListing();
		AddressSetView body = f.getBody();
		List<String> lines = new ArrayList<>();
		int count = 0;
		boolean cut = false;
		for (InstructionIterator it = listing.getInstructions(body, true); it.hasNext();) {
			Instruction ins = it.next();
			if (++count > MAX_INSTRUCTIONS) {
				cut = true;
				break;
			}
			Symbol label = program.getSymbolTable().getPrimarySymbol(ins.getAddress());
			if (label != null && !label.isDynamic() && !ins.getAddress().equals(f.getEntryPoint())) {
				lines.add(label.getName() + ":");
			}
			StringBuilder hex = new StringBuilder();
			try {
				for (byte b : ins.getBytes()) {
					hex.append(String.format("%02x", b & 0xff));
				}
			} catch (Exception e) {
				hex.append("??");
			}
			StringBuilder line = new StringBuilder();
			line.append(ins.getAddress()).append("  ").append(String.format("%-16s", hex)).append("  ")
					.append(ins.toString());
			Function called = null;
			for (Reference ref : ins.getReferencesFrom()) {
				if (ref.getReferenceType().isCall()) {
					called = program.getFunctionManager().getFunctionAt(ref.getToAddress());
					break;
				}
			}
			if (called != null) {
				line.append("    ; ").append(called.getName(true));
			}
			lines.add(line.toString());
		}
		Map<String, Object> out = new LinkedHashMap<>();
		out.put("function", f.getName(true));
		out.put("entry", f.getEntryPoint().toString());
		out.put("signature", f.getPrototypeString(false, false));
		out.put("lines", lines);
		out.put("cut", cut);
		return out;
	}

	Object imports(JsonObject req) {
		String needle = str(req, "filter").toLowerCase(Locale.ROOT);
		int offset = num(req, "offset", 0);
		int max = num(req, "max", 200);
		ExternalManager externals = program.getExternalManager();
		TreeMap<String, String[]> sorted = new TreeMap<>();
		for (SymbolIterator it = program.getSymbolTable().getExternalSymbols(); it.hasNext();) {
			Symbol s = it.next();
			ExternalLocation loc = externals.getExternalLocation(s);
			String library = loc != null ? loc.getLibraryName() : s.getParentNamespace().getName();
			String kind = s.getSymbolType() == SymbolType.FUNCTION ? "function" : "data";
			String key = library + "!" + s.getName() + "@" + s.getID();
			sorted.put(key, new String[] { library, s.getName(), kind });
		}
		List<Object> items = new ArrayList<>();
		int total = 0;
		for (String[] row : sorted.values()) {
			if (!matches(row[0] + "!" + row[1], needle)) {
				continue;
			}
			if (total >= offset && items.size() < max) {
				items.add(row);
			}
			total++;
		}
		return page(items, total, offset);
	}

	Object exports(JsonObject req) {
		String needle = str(req, "filter").toLowerCase(Locale.ROOT);
		int offset = num(req, "offset", 0);
		int max = num(req, "max", 200);
		List<Object> items = new ArrayList<>();
		List<Address> addresses = new ArrayList<>();
		for (Iterator<Address> it = program.getSymbolTable().getExternalEntryPointIterator(); it.hasNext();) {
			addresses.add(it.next());
		}
		addresses.sort(Comparator.naturalOrder());
		int total = 0;
		for (Address a : addresses) {
			Symbol s = program.getSymbolTable().getPrimarySymbol(a);
			String name = s != null ? s.getName(true) : "(no name)";
			if (!matches(name, needle)) {
				continue;
			}
			if (total >= offset && items.size() < max) {
				Function f = program.getFunctionManager().getFunctionAt(a);
				items.add(new String[] { a.toString(), name, f != null ? "function" : "data" });
			}
			total++;
		}
		return page(items, total, offset);
	}

	Object strings(JsonObject req) {
		String needle = str(req, "filter").toLowerCase(Locale.ROOT);
		int offset = num(req, "offset", 0);
		int max = num(req, "max", 200);
		int minLength = num(req, "min_length", 4);
		List<Object> items = new ArrayList<>();
		int total = 0;
		for (Iterator<Data> it = DefinedStringIterator.forProgram(program); it.hasNext();) {
			Data d = it.next();
			StringDataInstance sdi = StringDataInstance.getStringDataInstance(d);
			String value = sdi.getStringValue();
			if (value == null || value.length() < minLength || !matches(value, needle)) {
				continue;
			}
			if (total >= offset && items.size() < max) {
				String shown = value.length() > MAX_STRING_CHARS ? value.substring(0, MAX_STRING_CHARS) + "..." : value;
				items.add(new Object[] { d.getAddress().toString(), shown, value.length(),
						d.getDataType().getName() });
			}
			total++;
		}
		return page(items, total, offset);
	}

	/** What TARGET names: an address, a function, a label or an imported name - its addresses. */
	List<Address> targets(String spec, List<String> named) {
		List<Address> out = new ArrayList<>();
		Address a = address(spec);
		if (a != null) {
			out.add(a);
			named.add(a.toString());
			return out;
		}
		String wanted = spec.trim();
		SymbolTable table = program.getSymbolTable();
		for (SymbolIterator it = table.getSymbols(wanted); it.hasNext() && out.size() < MAX_MATCHES;) {
			Symbol s = it.next();
			out.add(s.getAddress());
			named.add(s.getName(true) + " (" + s.getAddress() + ")");
		}
		if (out.isEmpty()) {
			for (Function f : functions(wanted)) {
				out.add(f.getEntryPoint());
				named.add(f.getName(true) + " (" + f.getEntryPoint() + ")");
			}
		}
		return out;
	}

	Object xrefs(JsonObject req) {
		String spec = str(req, "target");
		List<String> named = new ArrayList<>();
		List<Address> addresses = targets(spec, named);
		if (addresses.isEmpty()) {
			throw new Refusal("nothing is named or at " + spec + " (list_functions, list_imports and list_strings "
					+ "show names and addresses)");
		}
		Set<Address> wanted = new HashSet<>(addresses);
		// A call to an import goes to its thunk: the references to the thunks count too.
		for (Address a : addresses) {
			for (Function f : program.getFunctionManager().getFunctions(true)) {
				if (f.isThunk() && f.getThunkedFunction(true) != null
						&& f.getThunkedFunction(true).getEntryPoint().equals(a)) {
					wanted.add(f.getEntryPoint());
				}
			}
		}
		List<Object> items = new ArrayList<>();
		int total = 0;
		for (Address a : wanted) {
			for (ReferenceIterator it = program.getReferenceManager().getReferencesTo(a); it.hasNext();) {
				Reference ref = it.next();
				total++;
				if (items.size() < MAX_REFS) {
					Function from = program.getFunctionManager().getFunctionContaining(ref.getFromAddress());
					items.add(new String[] { ref.getFromAddress().toString(), ref.getReferenceType().getName(),
							from != null ? from.getName(true) : "", a.toString() });
				}
			}
		}
		Map<String, Object> out = new LinkedHashMap<>();
		out.put("target", named);
		out.put("total", total);
		out.put("items", items);
		return out;
	}

	Object calls(JsonObject req) {
		Function f = function(req);
		Map<String, Object> out = new LinkedHashMap<>();
		out.put("function", f.getName(true));
		out.put("entry", f.getEntryPoint().toString());
		out.put("signature", f.getPrototypeString(false, false));
		out.put("size", f.getBody().getNumAddresses());
		out.put("callers", names(f.getCallingFunctions(TaskMonitor.DUMMY)));
		out.put("callees", names(f.getCalledFunctions(TaskMonitor.DUMMY)));
		return out;
	}

	static List<String[]> names(Set<Function> functions) {
		List<Function> sorted = new ArrayList<>(functions);
		sorted.sort(Comparator.comparing(Function::getEntryPoint));
		List<String[]> out = new ArrayList<>();
		for (Function f : sorted) {
			if (out.size() >= MAX_REFS) {
				break;
			}
			out.add(new String[] { f.getEntryPoint().toString(), f.getName(true), f.isExternal() ? "import"
					: f.isThunk() ? "thunk" : "function" });
		}
		return out;
	}

	Object handle(JsonObject req) {
		switch (str(req, "op")) {
			case "info":
				return info();
			case "functions":
				return listFunctions(req);
			case "decompile":
				return decompile(req);
			case "disassemble":
				return disassemble(req);
			case "imports":
				return imports(req);
			case "exports":
				return exports(req);
			case "strings":
				return strings(req);
			case "xrefs":
				return xrefs(req);
			case "calls":
				return calls(req);
			default:
				throw new Refusal("unknown op");
		}
	}

	/** A refusal the Python server shows as it is (no stack trace, no class name). */
	static final class Refusal extends RuntimeException {
		private static final long serialVersionUID = 1L;

		Refusal(String message) {
			super(message);
		}
	}

	static String reply(Gson gson, long id, Object result, String error) {
		Map<String, Object> out = new LinkedHashMap<>();
		out.put("id", id);
		out.put("ok", error == null);
		if (error == null) {
			out.put("result", result);
		} else {
			out.put("error", error);
		}
		return gson.toJson(out);
	}

	static String why(Throwable e) {
		if (e instanceof Refusal) {
			return e.getMessage();
		}
		String message = e.getMessage();
		return e.getClass().getSimpleName() + (message == null ? "" : ": " + message);
	}

	@Override
	public void launch(GhidraApplicationLayout layout, String[] argv) throws Exception {
		PrintStream protocol = new PrintStream(new FileOutputStream(FileDescriptor.out), false, "UTF-8");
		System.setOut(System.err); // whatever Ghidra or a library prints goes to stderr, never into the protocol
		Gson gson = new GsonBuilder().disableHtmlEscaping().serializeNulls().create();
		try {
			if (argv.length < 3 || argv.length > 5) {
				throw new Refusal("usage: GhidraBridge INPUT NAME ANALYSIS_SECONDS [LANGUAGE [COMPILER]]");
			}
			Application.initializeApplication(layout, new HeadlessGhidraApplicationConfiguration());
			protocol.println(reply(gson, 0, load(new File(argv[0]), argv[1], Integer.parseInt(argv[2]),
					argv.length > 3 ? argv[3] : "", argv.length > 4 ? argv[4] : ""), null));
			protocol.flush();
		} catch (Throwable e) {
			protocol.println(reply(gson, 0, null, e instanceof Refusal ? e.getMessage()
					: "Ghidra could not import the file: " + why(e)));
			protocol.flush();
			System.exit(0);
			return;
		}
		BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
		String line;
		while ((line = in.readLine()) != null) {
			long id = -1;
			String answer;
			try {
				JsonObject req = JsonParser.parseString(line).getAsJsonObject();
				id = req.get("id").getAsLong();
				answer = reply(gson, id, handle(req), null);
			} catch (Throwable e) {
				answer = reply(gson, id, null, why(e));
			}
			protocol.println(answer);
			protocol.flush();
		}
		decompiler.dispose();
		program.release(this);
		System.exit(0);
	}
}
