// JadxBridge: the part of the jadx MCP server (sandbox-ai-mcp) that runs in the JVM. It loads ONE input file with
// jadx's library (jadx-core and the input plugins named below, nothing found on the class path by itself) and answers
// the Python server (src/server.py) over stdin/stdout, one JSON object per line:
//   request  {"id": N, "op": "...", ...}
//   answer   {"id": N, "ok": true, "result": {...}}  or  {"id": N, "ok": false, "error": "..."}
// The first line it writes is the answer to the load (id 0). It reads only the file it is given (a link the Python
// server made to the file it opened and checked) and writes only below java.io.tmpdir (jadx's temporary files of
// nested archives); it saves no sources, opens no socket and starts no process. Logging is off; System.out is
// pointed at stderr before jadx is touched, so nothing but answers reaches the protocol stream.
//
//   java ... -cp jadx-1.5.6-all.jar:BRIDGE_DIR JadxBridge INPUT
import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TreeSet;
import java.util.regex.Pattern;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import jadx.api.JadxArgs;
import jadx.api.JadxDecompiler;
import jadx.api.JavaClass;
import jadx.api.JavaField;
import jadx.api.JavaMethod;
import jadx.api.JavaNode;
import jadx.api.ResourceFile;
import jadx.api.ResourceType;
import jadx.api.ResourcesLoader;
import jadx.api.plugins.JadxPlugin;
import jadx.api.plugins.loader.JadxPluginLoader;
import jadx.core.dex.instructions.args.ArgType;
import jadx.core.xmlgen.ResContainer;
import jadx.plugins.input.aab.AabInputPlugin;
import jadx.plugins.input.apkm.ApkmInputPlugin;
import jadx.plugins.input.apks.ApksInputPlugin;
import jadx.plugins.input.dex.DexInputPlugin;
import jadx.plugins.input.java.JavaInputPlugin;
import jadx.plugins.input.smali.SmaliInputPlugin;
import jadx.plugins.input.xapk.XApkInputPlugin;
import jadx.plugins.kotlin.metadata.KotlinMetadataPlugin;
import jadx.plugins.kotlin.smap.KotlinSmapPlugin;

public final class JadxBridge {
	/** Bytes of a resource read at most (text or binary); the Python server pages what it shows. */
	static final int MAX_RESOURCE_BYTES = 4 << 20;
	/** Characters of one line shown by a search. */
	static final int MAX_LINE_CHARS = 200;

	/**
	 * The plugins jadx may use: the input formats and the two Kotlin plugins that restore names. Not loaded:
	 * java-convert (D8/dx conversion, not needed beside java-input), rename-mappings (reads mapping files), and
	 * anything else on the class path or in a plugins folder (jadx-cli's loader would also read installed ones).
	 */
	static List<JadxPlugin> plugins() {
		return Arrays.asList(new DexInputPlugin(), new JavaInputPlugin(), new SmaliInputPlugin(), new XApkInputPlugin(),
				new ApkmInputPlugin(), new ApksInputPlugin(), new AabInputPlugin(), new KotlinMetadataPlugin(),
				new KotlinSmapPlugin());
	}

	final JadxDecompiler jadx;
	final Map<String, JavaClass> byName = new HashMap<>();
	List<JavaClass> topClasses;
	List<ResourceFile> resources;
	/** Decoded tables (resources.arsc): file name -> its decoded files. */
	Map<String, ResContainer> tables;

	JadxBridge(File input, File outDir) {
		JadxArgs args = new JadxArgs();
		args.setInputFile(input);
		args.setOutDir(outDir); // never written: nothing is saved
		args.setThreadsCount(1);
		args.setDeobfuscationOn(false);
		args.setPluginLoader(new JadxPluginLoader() {
			@Override
			public List<JadxPlugin> load() {
				return plugins();
			}

			@Override
			public void close() {
			}
		});
		jadx = new JadxDecompiler(args);
	}

	Map<String, Object> load() {
		jadx.load();
		topClasses = new ArrayList<>(jadx.getClasses());
		topClasses.sort(Comparator.comparing(JavaClass::getFullName));
		for (JavaClass cls : jadx.getClassesWithInners()) {
			byName.putIfAbsent(cls.getFullName(), cls);
			byName.putIfAbsent(cls.getRawName(), cls);
			byName.putIfAbsent(cls.getRawName().replace('$', '.'), cls);
		}
		resources = jadx.getResources();
		return info();
	}

	Map<String, Object> info() {
		Map<String, Object> out = new LinkedHashMap<>();
		out.put("classes", topClasses.size());
		out.put("classes_with_inner", jadx.getClassesWithInners().size());
		TreeSet<String> packages = new TreeSet<>();
		for (JavaClass cls : topClasses) {
			packages.add(cls.getPackage());
		}
		out.put("packages", packages.size());
		out.put("resources", resources.size());
		ResourceFile manifest = manifest();
		out.put("manifest", manifest == null ? null : manifest.getDeobfName());
		out.put("errors", jadx.getErrorsCount());
		out.put("jadx", JadxDecompiler.getVersion());
		return out;
	}

	JavaClass cls(JsonObject req) {
		String name = str(req, "class");
		JavaClass cls = byName.get(name);
		if (cls == null) {
			throw new Refusal("no class " + name);
		}
		return cls;
	}

	static String str(JsonObject req, String key) {
		return req.has(key) && !req.get(key).isJsonNull() ? req.get(key).getAsString() : "";
	}

	static String type(ArgType type) {
		return type == null ? "" : type.toString();
	}

	Object classes() {
		List<String[]> out = new ArrayList<>();
		for (JavaClass cls : topClasses) {
			out.add(new String[] { cls.getFullName(), cls.getRawName() });
		}
		return out;
	}

	Object outline(JsonObject req) {
		JavaClass cls = cls(req);
		Map<String, Object> out = new LinkedHashMap<>();
		out.put("class", cls.getFullName());
		out.put("raw", cls.getRawName());
		out.put("access", cls.getAccessInfo().makeString(false).trim());
		out.put("kind", cls.getAccessInfo().isInterface() ? "interface"
				: cls.getAccessInfo().isEnum() ? "enum" : cls.getAccessInfo().isAnnotation() ? "annotation" : "class");
		out.put("super", type(cls.getClassNode().getSuperClass()));
		List<String> interfaces = new ArrayList<>();
		for (ArgType type : cls.getClassNode().getInterfaces()) {
			interfaces.add(type(type));
		}
		out.put("interfaces", interfaces);
		out.put("top", cls.getTopParentClass().getFullName());
		List<Map<String, Object>> fields = new ArrayList<>();
		for (JavaField field : cls.getFields()) {
			Map<String, Object> f = new LinkedHashMap<>();
			f.put("name", field.getName());
			f.put("type", type(field.getType()));
			f.put("access", field.getAccessFlags().makeString(false).trim());
			fields.add(f);
		}
		out.put("fields", fields);
		List<Map<String, Object>> methods = new ArrayList<>();
		for (JavaMethod method : cls.getMethods()) {
			methods.add(describe(method));
		}
		out.put("methods", methods);
		List<String> inner = new ArrayList<>();
		for (JavaClass in : cls.getInnerClasses()) {
			inner.add(in.getFullName());
		}
		out.put("inner", inner);
		return out;
	}

	static Map<String, Object> describe(JavaMethod method) {
		Map<String, Object> m = new LinkedHashMap<>();
		m.put("name", method.getName());
		m.put("signature", method.getMethodNode().getMethodInfo().getShortId());
		List<String> args = new ArrayList<>();
		for (ArgType arg : method.getArguments()) {
			args.add(type(arg));
		}
		m.put("args", args);
		m.put("returns", type(method.getReturnType()));
		m.put("access", method.getAccessFlags().makeString(false).trim());
		return m;
	}

	List<JavaMethod> methods(JavaClass cls, JsonObject req) {
		String name = str(req, "method");
		String id = str(req, "signature");
		List<JavaMethod> found = new ArrayList<>();
		for (JavaMethod method : cls.getMethods()) {
			String raw = method.getMethodNode().getMethodInfo().getName();
			if ((method.getName().equals(name) || raw.equals(name))
					&& (id.isEmpty() || method.getMethodNode().getMethodInfo().getShortId().equals(id))) {
				found.add(method);
			}
		}
		return found;
	}

	Object source(JsonObject req) {
		JavaClass top = cls(req).getTopParentClass();
		Map<String, Object> out = new LinkedHashMap<>();
		out.put("class", top.getFullName());
		out.put("code", top.getCode());
		return out;
	}

	Object method(JsonObject req) {
		JavaClass cls = cls(req);
		List<Map<String, Object>> out = new ArrayList<>();
		for (JavaMethod method : methods(cls, req)) {
			Map<String, Object> m = describe(method);
			m.put("code", method.getCodeStr());
			out.add(m);
		}
		Map<String, Object> result = new LinkedHashMap<>();
		result.put("class", cls.getFullName());
		result.put("methods", out);
		if (out.isEmpty()) {
			List<String> names = new ArrayList<>();
			for (JavaMethod method : cls.getMethods()) {
				names.add(method.getMethodNode().getMethodInfo().getShortId());
			}
			result.put("available", names);
		}
		return result;
	}

	Object smali(JsonObject req) {
		JavaClass cls = cls(req);
		Map<String, Object> out = new LinkedHashMap<>();
		out.put("class", cls.getFullName());
		out.put("code", cls.getSmali());
		return out;
	}

	static String nodeName(JavaNode node) {
		if (node instanceof JavaMethod) {
			JavaMethod method = (JavaMethod) node;
			return method.getDeclaringClass().getFullName() + "." + method.getMethodNode().getMethodInfo().getShortId();
		}
		if (node instanceof JavaField) {
			JavaField field = (JavaField) node;
			return field.getDeclaringClass().getFullName() + "." + field.getName();
		}
		return node.getFullName();
	}

	static String nodeKind(JavaNode node) {
		return node instanceof JavaMethod ? "method" : node instanceof JavaField ? "field" : "class";
	}

	Object usages(JsonObject req) {
		JavaClass cls = cls(req);
		String member = str(req, "method");
		String field = str(req, "field");
		List<JavaNode> targets = new ArrayList<>();
		if (!member.isEmpty()) {
			targets.addAll(methods(cls, req));
			if (targets.isEmpty()) {
				throw new Refusal("no method " + member + " in " + cls.getFullName());
			}
		} else if (!field.isEmpty()) {
			for (JavaField f : cls.getFields()) {
				if (f.getName().equals(field) || f.getRawName().equals(field)) {
					targets.add(f);
				}
			}
			if (targets.isEmpty()) {
				throw new Refusal("no field " + field + " in " + cls.getFullName());
			}
		} else {
			targets.add(cls);
		}
		List<Map<String, Object>> out = new ArrayList<>();
		for (JavaNode target : targets) {
			TreeSet<String> users = new TreeSet<>();
			Map<String, String> kinds = new HashMap<>();
			for (JavaNode user : target.getUseIn()) {
				String name = nodeName(user);
				users.add(name);
				kinds.put(name, nodeKind(user));
			}
			List<Map<String, Object>> used = new ArrayList<>();
			for (String name : users) {
				Map<String, Object> u = new LinkedHashMap<>();
				u.put("kind", kinds.get(name));
				u.put("name", name);
				used.add(u);
			}
			Map<String, Object> t = new LinkedHashMap<>();
			t.put("target", nodeName(target));
			t.put("used_in", used);
			out.add(t);
		}
		return out;
	}

	Object search(JsonObject req) {
		String query = str(req, "query");
		boolean ignoreCase = req.has("ignore_case") && req.get("ignore_case").getAsBoolean();
		String pkg = str(req, "package");
		int start = req.get("start").getAsInt();
		int max = req.get("max").getAsInt();
		long deadline = System.nanoTime() + req.get("budget_ms").getAsLong() * 1_000_000L;
		Pattern pattern = Pattern.compile(Pattern.quote(query), ignoreCase ? Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE : 0);
		List<Map<String, Object>> matches = new ArrayList<>();
		int index = start;
		int scanned = 0;
		for (; index < topClasses.size(); index++) {
			if (matches.size() >= max || (index > start && System.nanoTime() > deadline)) {
				break;
			}
			JavaClass cls = topClasses.get(index);
			if (!pkg.isEmpty() && !(cls.getPackage().equals(pkg) || cls.getPackage().startsWith(pkg + "."))) {
				continue;
			}
			boolean wasLoaded = !cls.loadingWouldRequireDecompilation();
			String code = cls.getCode();
			scanned++;
			if (pattern.matcher(code).find()) {
				String[] lines = code.split("\n", -1);
				for (int i = 0; i < lines.length && matches.size() < max; i++) {
					if (pattern.matcher(lines[i]).find()) {
						Map<String, Object> m = new LinkedHashMap<>();
						m.put("class", cls.getFullName());
						m.put("line", i + 1);
						String line = lines[i].trim();
						m.put("text", line.length() > MAX_LINE_CHARS ? line.substring(0, MAX_LINE_CHARS) + "..." : line);
						matches.add(m);
					}
				}
			}
			if (!wasLoaded) {
				cls.unload(); // a search keeps no code in memory
			}
		}
		Map<String, Object> out = new LinkedHashMap<>();
		out.put("matches", matches);
		out.put("next", index < topClasses.size() ? index : -1);
		out.put("scanned", scanned);
		out.put("total", topClasses.size());
		return out;
	}

	Object names(JsonObject req) {
		String query = str(req, "query").toLowerCase(Locale.ROOT);
		int max = req.get("max").getAsInt();
		List<Map<String, Object>> out = new ArrayList<>();
		for (JavaClass cls : jadx.getClassesWithInners()) {
			if (out.size() >= max) {
				break;
			}
			if (cls.getFullName().toLowerCase(Locale.ROOT).contains(query)) {
				out.add(hit("class", cls.getFullName()));
			}
			for (JavaMethod method : cls.getMethods()) {
				if (out.size() < max && method.getName().toLowerCase(Locale.ROOT).contains(query)) {
					out.add(hit("method", nodeName(method)));
				}
			}
			for (JavaField field : cls.getFields()) {
				if (out.size() < max && field.getName().toLowerCase(Locale.ROOT).contains(query)) {
					out.add(hit("field", nodeName(field) + " : " + type(field.getType())));
				}
			}
		}
		return out;
	}

	static Map<String, Object> hit(String kind, String name) {
		Map<String, Object> m = new LinkedHashMap<>();
		m.put("kind", kind);
		m.put("name", name);
		return m;
	}

	ResourceFile manifest() {
		for (ResourceFile rf : resources) {
			if (rf.getType() == ResourceType.MANIFEST) {
				return rf;
			}
		}
		return null;
	}

	Map<String, ResContainer> tables() {
		if (tables == null) {
			tables = new LinkedHashMap<>();
			for (ResourceFile rf : resources) {
				if (rf.getType() == ResourceType.ARSC) {
					ResContainer decoded = rf.loadContent();
					for (ResContainer sub : decoded.getSubFiles()) {
						tables.putIfAbsent(sub.getName(), sub);
					}
				}
			}
		}
		return tables;
	}

	static long size(ResourceFile rf) {
		if (rf.getZipEntry() != null) {
			return rf.getZipEntry().getUncompressedSize();
		}
		return new File(rf.getOriginalName()).length();
	}

	Object resources(JsonObject req) {
		List<Map<String, Object>> out = new ArrayList<>();
		for (ResourceFile rf : resources) {
			Map<String, Object> r = new LinkedHashMap<>();
			r.put("name", rf.getDeobfName());
			r.put("type", rf.getType().name().toLowerCase(Locale.ROOT));
			r.put("size", size(rf));
			out.add(r);
		}
		if (req.has("tables") && req.get("tables").getAsBoolean()) {
			for (String name : tables().keySet()) {
				Map<String, Object> r = new LinkedHashMap<>();
				r.put("name", name);
				r.put("type", "decoded from resources.arsc");
				r.put("size", null);
				out.add(r);
			}
		}
		return out;
	}

	Object resource(JsonObject req) {
		String name = str(req, "name");
		Map<String, Object> out = new LinkedHashMap<>();
		out.put("name", name);
		ResourceFile found = null;
		for (ResourceFile rf : resources) {
			if (rf.getDeobfName().equals(name) || rf.getOriginalName().equals(name)) {
				found = rf;
				break;
			}
		}
		if (found == null && name.equals("AndroidManifest.xml")) {
			found = manifest();
		}
		if (found == null) {
			ResContainer sub = tables().get(name);
			if (sub == null) {
				throw new Refusal("no resource " + name);
			}
			return content(out, sub);
		}
		ResourceType type = found.getType();
		if (type == ResourceType.ARSC) {
			out.put("text", null);
			List<String> files = new ArrayList<>();
			for (ResContainer sub : found.loadContent().getSubFiles()) {
				files.add(sub.getName());
			}
			out.put("files", files);
			return out;
		}
		if (type == ResourceType.MANIFEST || type == ResourceType.XML) {
			return content(out, found.loadContent());
		}
		return raw(out, found);
	}

	Map<String, Object> content(Map<String, Object> out, ResContainer container) {
		switch (container.getDataType()) {
			case TEXT:
			case RES_TABLE:
				out.put("text", container.getText().getCodeStr());
				return out;
			case DECODED_DATA:
				return bytes(out, container.getDecodedData(), container.getDecodedData().length);
			case RES_LINK:
			default:
				return raw(out, container.getResLink());
		}
	}

	Map<String, Object> raw(Map<String, Object> out, ResourceFile rf) {
		try {
			byte[][] holder = new byte[1][];
			long[] total = new long[1];
			ResourcesLoader.decodeStream(rf, (size, is) -> {
				total[0] = size;
				holder[0] = readUpTo(is, MAX_RESOURCE_BYTES);
				return null;
			});
			return bytes(out, holder[0], total[0]);
		} catch (Exception e) {
			throw new Refusal("cannot read " + rf.getDeobfName() + ": " + e.getMessage());
		}
	}

	static byte[] readUpTo(InputStream is, int limit) throws java.io.IOException {
		ByteArrayOutputStream buffer = new ByteArrayOutputStream();
		byte[] chunk = new byte[64 * 1024];
		int read;
		while (buffer.size() < limit && (read = is.read(chunk, 0, Math.min(chunk.length, limit - buffer.size()))) > 0) {
			buffer.write(chunk, 0, read);
		}
		return buffer.toByteArray();
	}

	static Map<String, Object> bytes(Map<String, Object> out, byte[] data, long total) {
		out.put("size", total);
		boolean text = true;
		for (int i = 0; i < Math.min(data.length, 8192); i++) {
			if (data[i] == 0) {
				text = false;
				break;
			}
		}
		if (text) {
			try {
				out.put("text", StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
						.onUnmappableCharacter(CodingErrorAction.REPORT).decode(java.nio.ByteBuffer.wrap(data)).toString());
				out.put("cut", data.length < total);
				return out;
			} catch (CharacterCodingException e) {
				// not UTF-8: shown as bytes
			}
		}
		out.put("text", null);
		StringBuilder hex = new StringBuilder();
		for (int i = 0; i < Math.min(data.length, 256); i++) {
			hex.append(String.format("%02x", data[i] & 0xff));
		}
		out.put("head_hex", hex.toString());
		return out;
	}

	Object handle(JsonObject req) {
		switch (str(req, "op")) {
			case "info":
				return info();
			case "classes":
				return classes();
			case "outline":
				return outline(req);
			case "source":
				return source(req);
			case "method":
				return method(req);
			case "smali":
				return smali(req);
			case "usages":
				return usages(req);
			case "search":
				return search(req);
			case "names":
				return names(req);
			case "resources":
				return resources(req);
			case "resource":
				return resource(req);
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

	public static void main(String[] argv) throws Exception {
		PrintStream protocol = new PrintStream(new FileOutputStream(FileDescriptor.out), false, "UTF-8");
		System.setOut(System.err); // whatever jadx or a library prints goes to stderr, never into the protocol
		((ch.qos.logback.classic.Logger) org.slf4j.LoggerFactory.getLogger(org.slf4j.Logger.ROOT_LOGGER_NAME))
				.setLevel(ch.qos.logback.classic.Level.OFF);
		File input = new File(argv[0]);
		File outDir = new File(System.getProperty("java.io.tmpdir"), "never-written");
		Gson gson = new GsonBuilder().disableHtmlEscaping().serializeNulls().create();
		JadxBridge bridge;
		try {
			bridge = new JadxBridge(input, outDir);
			protocol.println(reply(gson, 0, bridge.load(), null));
			protocol.flush();
		} catch (Throwable e) {
			protocol.println(reply(gson, 0, null, "jadx could not load the file: " + why(e)));
			protocol.flush();
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
				answer = reply(gson, id, bridge.handle(req), null);
			} catch (Throwable e) {
				answer = reply(gson, id, null, why(e));
			}
			protocol.println(answer);
			protocol.flush();
		}
	}
}
