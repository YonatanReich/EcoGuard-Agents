//#region node_modules/@loaders.gl/loader-utils/dist/lib/env-utils/assert.js
/**
* Throws an `Error` with the optional `message` if `condition` is falsy
* @note Replacement for the external assert method to reduce bundle size
*/
function assert$6(condition, message) {
	if (!condition) throw new Error(message || "loader assertion failed.");
}
//#endregion
//#region node_modules/@loaders.gl/loader-utils/dist/lib/env-utils/globals.js
var globals$1 = {
	self: typeof self !== "undefined" && self,
	window: typeof window !== "undefined" && window,
	global: typeof global !== "undefined" && global,
	document: typeof document !== "undefined" && document
};
globals$1.self || globals$1.window || globals$1.global;
globals$1.window || globals$1.self || globals$1.global;
globals$1.global || globals$1.self || globals$1.window;
globals$1.document;
/** true if running in a browser */
var isBrowser$2 = Boolean(typeof process !== "object" || String(process) !== "[object process]" || process.browser);
var matches$1 = typeof process !== "undefined" && process.version && /v([0-9]*)/.exec(process.version);
matches$1 && parseFloat(matches$1[1]);
//#endregion
//#region node_modules/@probe.gl/env/dist/lib/globals.js
var window_$1 = globalThis;
globalThis.document;
var process_ = globalThis.process || {};
globalThis.console;
var navigator_ = globalThis.navigator || {};
//#endregion
//#region node_modules/@probe.gl/env/dist/lib/is-electron.js
function isElectron(mockUserAgent) {
	if (typeof window !== "undefined" && window.process?.type === "renderer") return true;
	if (typeof process !== "undefined" && Boolean(process.versions?.["electron"])) return true;
	const realUserAgent = typeof navigator !== "undefined" && navigator.userAgent;
	const userAgent = mockUserAgent || realUserAgent;
	return Boolean(userAgent && userAgent.indexOf("Electron") >= 0);
}
//#endregion
//#region node_modules/@probe.gl/env/dist/lib/is-browser.js
/** Check if in browser by duck-typing Node context */
function isBrowser$1() {
	return !(typeof process === "object" && String(process) === "[object process]" && !process?.browser) || isElectron();
}
//#endregion
//#region node_modules/@probe.gl/env/dist/lib/get-browser.js
function getBrowser(mockUserAgent) {
	if (!mockUserAgent && !isBrowser$1()) return "Node";
	if (isElectron(mockUserAgent)) return "Electron";
	if ((mockUserAgent || navigator_.userAgent || "").indexOf("Edge") > -1) return "Edge";
	if (globalThis.chrome) return "Chrome";
	if (globalThis.safari) return "Safari";
	if (globalThis.mozInnerScreenX) return "Firefox";
	return "Unknown";
}
//#endregion
//#region node_modules/@probe.gl/env/dist/index.js
var VERSION$2 = "4.1.1";
//#endregion
//#region node_modules/@probe.gl/log/dist/utils/assert.js
function assert$5(condition, message) {
	if (!condition) throw new Error(message || "Assertion failed");
}
//#endregion
//#region node_modules/@probe.gl/log/dist/loggers/log-utils.js
/**
* Get logLevel from first argument:
* - log(logLevel, message, args) => logLevel
* - log(message, args) => 0
* - log({logLevel, ...}, message, args) => logLevel
* - log({logLevel, message, args}) => logLevel
*/
function normalizeLogLevel(logLevel) {
	if (!logLevel) return 0;
	let resolvedLevel;
	switch (typeof logLevel) {
		case "number":
			resolvedLevel = logLevel;
			break;
		case "object":
			resolvedLevel = logLevel.logLevel || logLevel.priority || 0;
			break;
		default: return 0;
	}
	assert$5(Number.isFinite(resolvedLevel) && resolvedLevel >= 0);
	return resolvedLevel;
}
/**
* "Normalizes" the various argument patterns into an object with known types
* - log(logLevel, message, args) => {logLevel, message, args}
* - log(message, args) => {logLevel: 0, message, args}
* - log({logLevel, ...}, message, args) => {logLevel, message, args}
* - log({logLevel, message, args}) => {logLevel, message, args}
*/
function normalizeArguments(opts) {
	const { logLevel, message } = opts;
	opts.logLevel = normalizeLogLevel(logLevel);
	const args = opts.args ? Array.from(opts.args) : [];
	while (args.length && args.shift() !== message);
	switch (typeof logLevel) {
		case "string":
		case "function":
			if (message !== void 0) args.unshift(message);
			opts.message = logLevel;
			break;
		case "object":
			Object.assign(opts, logLevel);
			break;
		default:
	}
	if (typeof opts.message === "function") opts.message = opts.message();
	const messageType = typeof opts.message;
	assert$5(messageType === "string" || messageType === "object");
	return Object.assign(opts, { args }, opts.opts);
}
//#endregion
//#region node_modules/@probe.gl/log/dist/loggers/base-log.js
var noop = () => {};
/**
* Base logger that implements log level handling and once de-duplication.
* Concrete loggers implement `_emit` to perform actual output.
*/
var BaseLog = class {
	constructor({ level = 0 } = {}) {
		this.userData = {};
		this._onceCache = /* @__PURE__ */ new Set();
		this._level = level;
	}
	set level(newLevel) {
		this.setLevel(newLevel);
	}
	get level() {
		return this.getLevel();
	}
	setLevel(level) {
		this._level = level;
		return this;
	}
	getLevel() {
		return this._level;
	}
	warn(message, ...args) {
		return this._log("warn", 0, message, args, { once: true });
	}
	error(message, ...args) {
		return this._log("error", 0, message, args);
	}
	log(logLevel, message, ...args) {
		return this._log("log", logLevel, message, args);
	}
	info(logLevel, message, ...args) {
		return this._log("info", logLevel, message, args);
	}
	once(logLevel, message, ...args) {
		return this._log("once", logLevel, message, args, { once: true });
	}
	_log(type, logLevel, message, args, options = {}) {
		const normalized = normalizeArguments({
			logLevel,
			message,
			args: this._buildArgs(logLevel, message, args),
			opts: options
		});
		return this._createLogFunction(type, normalized, options);
	}
	_buildArgs(logLevel, message, args) {
		return [
			logLevel,
			message,
			...args
		];
	}
	_createLogFunction(type, normalized, options) {
		if (!this._shouldLog(normalized.logLevel)) return noop;
		const tag = this._getOnceTag(options.tag ?? normalized.tag ?? normalized.message);
		if ((options.once || normalized.once) && tag !== void 0) {
			if (this._onceCache.has(tag)) return noop;
			this._onceCache.add(tag);
		}
		return this._emit(type, normalized);
	}
	_shouldLog(logLevel) {
		return this.getLevel() >= normalizeLogLevel(logLevel);
	}
	_getOnceTag(tag) {
		if (tag === void 0) return;
		try {
			return typeof tag === "string" ? tag : String(tag);
		} catch {
			return;
		}
	}
};
//#endregion
//#region node_modules/@probe.gl/log/dist/utils/local-storage.js
function getStorage(type) {
	try {
		const storage = window[type];
		const x = "__storage_test__";
		storage.setItem(x, x);
		storage.removeItem(x);
		return storage;
	} catch (e) {
		return null;
	}
}
var LocalStorage = class {
	constructor(id, defaultConfig, type = "sessionStorage") {
		this.storage = getStorage(type);
		this.id = id;
		this.config = defaultConfig;
		this._loadConfiguration();
	}
	getConfiguration() {
		return this.config;
	}
	setConfiguration(configuration) {
		Object.assign(this.config, configuration);
		if (this.storage) {
			const serialized = JSON.stringify(this.config);
			this.storage.setItem(this.id, serialized);
		}
	}
	_loadConfiguration() {
		let configuration = {};
		if (this.storage) {
			const serializedConfiguration = this.storage.getItem(this.id);
			configuration = serializedConfiguration ? JSON.parse(serializedConfiguration) : {};
		}
		Object.assign(this.config, configuration);
		return this;
	}
};
//#endregion
//#region node_modules/@probe.gl/log/dist/utils/formatters.js
/**
* Format time
*/
function formatTime(ms) {
	let formatted;
	if (ms < 10) formatted = `${ms.toFixed(2)}ms`;
	else if (ms < 100) formatted = `${ms.toFixed(1)}ms`;
	else if (ms < 1e3) formatted = `${ms.toFixed(0)}ms`;
	else formatted = `${(ms / 1e3).toFixed(2)}s`;
	return formatted;
}
function leftPad(string, length = 8) {
	const padLength = Math.max(length - string.length, 0);
	return `${" ".repeat(padLength)}${string}`;
}
//#endregion
//#region node_modules/@probe.gl/log/dist/utils/color.js
var COLOR;
(function(COLOR) {
	COLOR[COLOR["BLACK"] = 30] = "BLACK";
	COLOR[COLOR["RED"] = 31] = "RED";
	COLOR[COLOR["GREEN"] = 32] = "GREEN";
	COLOR[COLOR["YELLOW"] = 33] = "YELLOW";
	COLOR[COLOR["BLUE"] = 34] = "BLUE";
	COLOR[COLOR["MAGENTA"] = 35] = "MAGENTA";
	COLOR[COLOR["CYAN"] = 36] = "CYAN";
	COLOR[COLOR["WHITE"] = 37] = "WHITE";
	COLOR[COLOR["BRIGHT_BLACK"] = 90] = "BRIGHT_BLACK";
	COLOR[COLOR["BRIGHT_RED"] = 91] = "BRIGHT_RED";
	COLOR[COLOR["BRIGHT_GREEN"] = 92] = "BRIGHT_GREEN";
	COLOR[COLOR["BRIGHT_YELLOW"] = 93] = "BRIGHT_YELLOW";
	COLOR[COLOR["BRIGHT_BLUE"] = 94] = "BRIGHT_BLUE";
	COLOR[COLOR["BRIGHT_MAGENTA"] = 95] = "BRIGHT_MAGENTA";
	COLOR[COLOR["BRIGHT_CYAN"] = 96] = "BRIGHT_CYAN";
	COLOR[COLOR["BRIGHT_WHITE"] = 97] = "BRIGHT_WHITE";
})(COLOR || (COLOR = {}));
var BACKGROUND_INCREMENT = 10;
function getColor(color) {
	if (typeof color !== "string") return color;
	color = color.toUpperCase();
	return COLOR[color] || COLOR.WHITE;
}
function addColor(string, color, background) {
	if (!isBrowser$1 && typeof string === "string") {
		if (color) string = `\u001b[${getColor(color)}m${string}\u001b[39m`;
		if (background) string = `\u001b[${getColor(background) + BACKGROUND_INCREMENT}m${string}\u001b[49m`;
	}
	return string;
}
//#endregion
//#region node_modules/@probe.gl/log/dist/utils/autobind.js
/**
* Binds the "this" argument of all functions on a class instance to the instance
* @param obj - class instance (typically a react component)
*/
function autobind(obj, predefined = ["constructor"]) {
	const propNames = Object.getOwnPropertyNames(Object.getPrototypeOf(obj));
	const object = obj;
	for (const key of propNames) {
		const value = object[key];
		if (typeof value === "function") {
			if (!predefined.find((name) => key === name)) object[key] = value.bind(obj);
		}
	}
}
//#endregion
//#region node_modules/@probe.gl/log/dist/utils/hi-res-timestamp.js
/** Get best timer available. */
function getHiResTimestamp$1() {
	let timestamp;
	if (isBrowser$1() && window_$1.performance) timestamp = window_$1?.performance?.now?.();
	else if ("hrtime" in process_) {
		const timeParts = process_?.hrtime?.();
		timestamp = timeParts[0] * 1e3 + timeParts[1] / 1e6;
	} else timestamp = Date.now();
	return timestamp;
}
//#endregion
//#region node_modules/@probe.gl/log/dist/loggers/probe-log.js
var originalConsole = {
	debug: isBrowser$1() ? console.debug || console.log : console.log,
	log: console.log,
	info: console.info,
	warn: console.warn,
	error: console.error
};
var DEFAULT_LOG_CONFIGURATION = {
	enabled: true,
	level: 0
};
/** A console wrapper */
var ProbeLog = class extends BaseLog {
	constructor({ id } = { id: "" }) {
		super({ level: 0 });
		this.VERSION = VERSION$2;
		this._startTs = getHiResTimestamp$1();
		this._deltaTs = getHiResTimestamp$1();
		this.userData = {};
		this.LOG_THROTTLE_TIMEOUT = 0;
		this.id = id;
		this.userData = {};
		this._storage = new LocalStorage(`__probe-${this.id}__`, { [this.id]: DEFAULT_LOG_CONFIGURATION });
		this.timeStamp(`${this.id} started`);
		autobind(this);
		Object.seal(this);
	}
	isEnabled() {
		return this._getConfiguration().enabled;
	}
	getLevel() {
		return this._getConfiguration().level;
	}
	/** @return milliseconds, with fractions */
	getTotal() {
		return Number((getHiResTimestamp$1() - this._startTs).toPrecision(10));
	}
	/** @return milliseconds, with fractions */
	getDelta() {
		return Number((getHiResTimestamp$1() - this._deltaTs).toPrecision(10));
	}
	/** @deprecated use logLevel */
	set priority(newPriority) {
		this.level = newPriority;
	}
	/** @deprecated use logLevel */
	get priority() {
		return this.level;
	}
	/** @deprecated use logLevel */
	getPriority() {
		return this.level;
	}
	enable(enabled = true) {
		this._updateConfiguration({ enabled });
		return this;
	}
	setLevel(level) {
		this._updateConfiguration({ level });
		return this;
	}
	/** return the current status of the setting */
	get(setting) {
		return this._getConfiguration()[setting];
	}
	set(setting, value) {
		this._updateConfiguration({ [setting]: value });
	}
	/** Logs the current settings as a table */
	settings() {
		if (console.table) console.table(this._storage.config);
		else console.log(this._storage.config);
	}
	assert(condition, message) {
		if (!condition) throw new Error(message || "Assertion failed");
	}
	warn(message, ...args) {
		return this._log("warn", 0, message, args, {
			method: originalConsole.warn,
			once: true
		});
	}
	error(message, ...args) {
		return this._log("error", 0, message, args, { method: originalConsole.error });
	}
	/** Print a deprecation warning */
	deprecated(oldUsage, newUsage) {
		return this.warn(`\`${oldUsage}\` is deprecated and will be removed \
in a later version. Use \`${newUsage}\` instead`);
	}
	/** Print a removal warning */
	removed(oldUsage, newUsage) {
		return this.error(`\`${oldUsage}\` has been removed. Use \`${newUsage}\` instead`);
	}
	probe(logLevel, message, ...args) {
		return this._log("log", logLevel, message, args, {
			method: originalConsole.log,
			time: true,
			once: true
		});
	}
	log(logLevel, message, ...args) {
		return this._log("log", logLevel, message, args, { method: originalConsole.debug });
	}
	info(logLevel, message, ...args) {
		return this._log("info", logLevel, message, args, { method: console.info });
	}
	once(logLevel, message, ...args) {
		return this._log("once", logLevel, message, args, {
			method: originalConsole.debug || originalConsole.info,
			once: true
		});
	}
	/** Logs an object as a table */
	table(logLevel, table, columns) {
		if (table) return this._log("table", logLevel, table, columns && [columns] || [], {
			method: console.table || noop,
			tag: getTableHeader(table)
		});
		return noop;
	}
	time(logLevel, message) {
		return this._log("time", logLevel, message, [], { method: console.time ? console.time : console.info });
	}
	timeEnd(logLevel, message) {
		return this._log("time", logLevel, message, [], { method: console.timeEnd ? console.timeEnd : console.info });
	}
	timeStamp(logLevel, message) {
		return this._log("time", logLevel, message, [], { method: console.timeStamp || noop });
	}
	group(logLevel, message, opts = { collapsed: false }) {
		const method = (opts.collapsed ? console.groupCollapsed : console.group) || console.info;
		return this._log("group", logLevel, message, [], { method });
	}
	groupCollapsed(logLevel, message, opts = {}) {
		return this.group(logLevel, message, Object.assign({}, opts, { collapsed: true }));
	}
	groupEnd(logLevel) {
		return this._log("groupEnd", logLevel, "", [], { method: console.groupEnd || noop });
	}
	withGroup(logLevel, message, func) {
		this.group(logLevel, message)();
		try {
			func();
		} finally {
			this.groupEnd(logLevel)();
		}
	}
	trace() {
		if (console.trace) console.trace();
	}
	_shouldLog(logLevel) {
		return this.isEnabled() && super._shouldLog(logLevel);
	}
	_emit(_type, normalized) {
		const method = normalized.method;
		assert$5(method);
		normalized.total = this.getTotal();
		normalized.delta = this.getDelta();
		this._deltaTs = getHiResTimestamp$1();
		const message = decorateMessage(this.id, normalized.message, normalized);
		return method.bind(console, message, ...normalized.args);
	}
	_getConfiguration() {
		if (!this._storage.config[this.id]) this._updateConfiguration(DEFAULT_LOG_CONFIGURATION);
		return this._storage.config[this.id];
	}
	_updateConfiguration(configuration) {
		const currentConfiguration = this._storage.config[this.id] || { ...DEFAULT_LOG_CONFIGURATION };
		this._storage.setConfiguration({ [this.id]: {
			...currentConfiguration,
			...configuration
		} });
	}
};
ProbeLog.VERSION = VERSION$2;
function decorateMessage(id, message, opts) {
	if (typeof message === "string") {
		const time = opts.time ? leftPad(formatTime(opts.total)) : "";
		message = opts.time ? `${id}: ${time}  ${message}` : `${id}: ${message}`;
		message = addColor(message, opts.color, opts.background);
	}
	return message;
}
function getTableHeader(table) {
	for (const key in table) for (const title in table[key]) return title || "untitled";
	return "empty";
}
//#endregion
//#region node_modules/@probe.gl/log/dist/init.js
globalThis.probe = {};
new ProbeLog({ id: "@probe.gl/log" });
var version = "4.4.5"[0] >= "0" && "4.4.5"[0] <= "9" ? `v4.4.5` : "";
function createLog() {
	const log = new ProbeLog({ id: "loaders.gl" });
	globalThis.loaders ||= {};
	globalThis.loaders.log = log;
	globalThis.loaders.version = version;
	globalThis.probe ||= {};
	globalThis.probe.loaders = log;
	return log;
}
var log$1 = createLog();
//#endregion
//#region node_modules/@loaders.gl/loader-utils/dist/lib/javascript-utils/is-type.js
/** Checks whether a value is a boolean */
var isBoolean = (value) => typeof value === "boolean";
/** Checks whether a value is a function */
var isFunction = (value) => typeof value === "function";
/** Checks whether a value is a non-null object */
var isObject = (value) => value !== null && typeof value === "object";
/** Checks whether a value is a plain object (created by the Object constructor) */
var isPureObject = (value) => isObject(value) && value.constructor === {}.constructor;
/** Checks whether a value is an ArrayBuffer */
var isSharedArrayBuffer = (value) => typeof SharedArrayBuffer !== "undefined" && value instanceof SharedArrayBuffer;
/** Checks whether a value is ArrayBuffer-like */
var isArrayBufferLike = (value) => isObject(value) && typeof value.byteLength === "number" && typeof value.slice === "function";
/** Checks whether a value implements the iterable protocol */
var isIterable = (value) => Boolean(value) && isFunction(value[Symbol.iterator]);
/** Checks whether a value implements the async iterable protocol */
var isAsyncIterable = (value) => Boolean(value) && isFunction(value[Symbol.asyncIterator]);
/** Checks whether a value is a fetch Response or a duck-typed equivalent */
var isResponse = (value) => typeof Response !== "undefined" && value instanceof Response || isObject(value) && isFunction(value.arrayBuffer) && isFunction(value.text) && isFunction(value.json);
/** Checks whether a value is a Blob */
var isBlob = (value) => typeof Blob !== "undefined" && value instanceof Blob;
/** Checks whether a value looks like a DOM ReadableStream */
var isReadableDOMStream = (value) => typeof ReadableStream !== "undefined" && value instanceof ReadableStream || isObject(value) && isFunction(value.tee) && isFunction(value.cancel) && isFunction(value.getReader);
/** Checks whether a value looks like a Node.js readable stream */
var isReadableNodeStream = (value) => isObject(value) && isFunction(value.read) && isFunction(value.pipe) && isBoolean(value.readable);
/** Checks whether a value is any readable stream (DOM or Node.js) */
var isReadableStream = (value) => isReadableDOMStream(value) || isReadableNodeStream(value);
//#endregion
//#region node_modules/@loaders.gl/loader-utils/dist/lib/option-utils/merge-options.js
/**
*
* @param baseOptions Can be undefined, in which case a fresh options object will be minted
* @param newOptions
* @returns
*/
function mergeOptions(baseOptions, newOptions) {
	return mergeOptionsRecursively(baseOptions || {}, newOptions);
}
function mergeOptionsRecursively(baseOptions, newOptions, level = 0) {
	if (level > 3) return newOptions;
	const options = { ...baseOptions };
	for (const [key, newValue] of Object.entries(newOptions)) if (newValue && typeof newValue === "object" && !Array.isArray(newValue)) options[key] = mergeOptionsRecursively(options[key] || {}, newOptions[key], level + 1);
	else options[key] = newOptions[key];
	return options;
}
//#endregion
//#region node_modules/@loaders.gl/worker-utils/dist/lib/npm-tag.js
/**
* NPM tag to use when loading modules from unpkg.com
* 'beta' on beta branch, 'latest' on prod branch
* @note Change between 'beta' and 'latest' depending on whether publishing alpha or prod releases
* @todo - unpkg.com doesn't seem to have a `latest` specifier for alpha releases...
*/
var NPM_TAG = "latest";
//#endregion
//#region node_modules/@loaders.gl/worker-utils/dist/lib/env-utils/version.js
function getVersion() {
	if (!globalThis._loadersgl_?.version) {
		globalThis._loadersgl_ = globalThis._loadersgl_ || {};
		globalThis._loadersgl_.version = "4.4.5";
	}
	return globalThis._loadersgl_.version;
}
var VERSION = getVersion();
//#endregion
//#region node_modules/@loaders.gl/worker-utils/dist/lib/env-utils/assert.js
/** Throws an `Error` with the optional `message` if `condition` is falsy */
function assert$4(condition, message) {
	if (!condition) throw new Error(message || "loaders.gl assertion failed.");
}
//#endregion
//#region node_modules/@loaders.gl/worker-utils/dist/lib/env-utils/globals.js
var globals = {
	self: typeof self !== "undefined" && self,
	window: typeof window !== "undefined" && window,
	global: typeof global !== "undefined" && global,
	document: typeof document !== "undefined" && document
};
globals.self || globals.window || globals.global;
globals.window || globals.self || globals.global;
globals.global || globals.self || globals.window;
globals.document;
/** true if running in the browser, false if running in Node.js */
var isBrowser = typeof process !== "object" || String(process) !== "[object process]" || process.browser;
/** true if running on a mobile device */
var isMobile = typeof window !== "undefined" && typeof window.orientation !== "undefined";
var matches = typeof process !== "undefined" && process.version && /v([0-9]*)/.exec(process.version);
matches && parseFloat(matches[1]);
//#endregion
//#region node_modules/@loaders.gl/worker-utils/dist/lib/worker-farm/worker-job.js
/**
* Represents one Job handled by a WorkerPool or WorkerFarm
*/
var WorkerJob = class {
	name;
	workerThread;
	isRunning = true;
	/** Promise that resolves when Job is done */
	result;
	_resolve = () => {};
	_reject = () => {};
	constructor(jobName, workerThread) {
		this.name = jobName;
		this.workerThread = workerThread;
		this.result = new Promise((resolve, reject) => {
			this._resolve = resolve;
			this._reject = reject;
		});
	}
	/**
	* Send a message to the job's worker thread
	* @param data any data structure, ideally consisting mostly of transferrable objects
	*/
	postMessage(type, payload) {
		this.workerThread.postMessage({
			source: "loaders.gl",
			type,
			payload
		});
	}
	/**
	* Call to resolve the `result` Promise with the supplied value
	*/
	done(value) {
		assert$4(this.isRunning);
		this.isRunning = false;
		this._resolve(value);
	}
	/**
	* Call to reject the `result` Promise with the supplied error
	*/
	error(error) {
		assert$4(this.isRunning);
		this.isRunning = false;
		this._reject(error);
	}
};
//#endregion
//#region node_modules/@loaders.gl/worker-utils/dist/lib/node/worker_threads-browser.js
/** Browser polyfill for Node.js built-in `worker_threads` module.
* These fills are non-functional, and just intended to ensure that
* `import 'worker_threads` doesn't break browser builds.
* The replacement is done in package.json browser field
*/
var NodeWorker = class {
	terminate() {}
};
//#endregion
//#region node_modules/@loaders.gl/worker-utils/dist/lib/worker-utils/get-loadable-worker-url.js
var workerURLCache = /* @__PURE__ */ new Map();
/**
* Creates a loadable URL from worker source or URL
* that can be used to create `Worker` instances.
* Due to CORS issues it may be necessary to wrap a URL in a small importScripts
* @param props
* @param props.source Worker source
* @param props.url Worker URL
* @returns loadable url
*/
function getLoadableWorkerURL(props) {
	assert$4(props.source && !props.url || !props.source && props.url);
	let workerURL = workerURLCache.get(props.source || props.url);
	if (!workerURL) {
		if (props.url) {
			workerURL = getLoadableWorkerURLFromURL(props.url);
			workerURLCache.set(props.url, workerURL);
		}
		if (props.source) {
			workerURL = getLoadableWorkerURLFromSource(props.source);
			workerURLCache.set(props.source, workerURL);
		}
	}
	assert$4(workerURL);
	return workerURL;
}
/**
* Build a loadable worker URL from worker URL
* @param url
* @returns loadable URL
*/
function getLoadableWorkerURLFromURL(url) {
	if (!url.startsWith("http")) return url;
	return getLoadableWorkerURLFromSource(buildScriptSource(url));
}
/**
* Build a loadable worker URL from worker source
* @param workerSource
* @returns loadable url
*/
function getLoadableWorkerURLFromSource(workerSource) {
	const blob = new Blob([workerSource], { type: "application/javascript" });
	return URL.createObjectURL(blob);
}
/**
* Per spec, worker cannot be initialized with a script from a different origin
* However a local worker script can still import scripts from other origins,
* so we simply build a wrapper script.
*
* @param workerUrl
* @returns source
*/
function buildScriptSource(workerUrl) {
	return `\
try {
  importScripts('${workerUrl}');
} catch (error) {
  console.error(error);
  throw error;
}`;
}
//#endregion
//#region node_modules/@loaders.gl/worker-utils/dist/lib/worker-utils/get-transfer-list.js
/**
* Returns an array of Transferrable objects that can be used with postMessage
* https://developer.mozilla.org/en-US/docs/Web/API/Worker/postMessage
* @param object data to be sent via postMessage
* @param recursive - not for application use
* @param transfers - not for application use
* @returns a transfer list that can be passed to postMessage
*/
function getTransferList(object, recursive = true, transfers) {
	const transfersSet = transfers || /* @__PURE__ */ new Set();
	if (!object) {} else if (isTransferable(object)) transfersSet.add(object);
	else if (isTransferable(object.buffer)) transfersSet.add(object.buffer);
	else if (ArrayBuffer.isView(object)) {} else if (recursive && typeof object === "object") for (const key in object) getTransferList(object[key], recursive, transfersSet);
	return transfers === void 0 ? Array.from(transfersSet) : [];
}
function isTransferable(object) {
	if (!object) return false;
	if (object instanceof ArrayBuffer) return true;
	if (typeof MessagePort !== "undefined" && object instanceof MessagePort) return true;
	if (typeof ImageBitmap !== "undefined" && object instanceof ImageBitmap) return true;
	if (typeof OffscreenCanvas !== "undefined" && object instanceof OffscreenCanvas) return true;
	return false;
}
//#endregion
//#region node_modules/@loaders.gl/worker-utils/dist/lib/worker-farm/worker-thread.js
var NOOP = () => {};
/**
* Represents one worker thread
*/
var WorkerThread = class {
	name;
	source;
	url;
	terminated = false;
	worker;
	onMessage;
	onError;
	_loadableURL = "";
	/** Checks if workers are supported on this platform */
	static isSupported() {
		return typeof Worker !== "undefined" && isBrowser || typeof NodeWorker !== "undefined" && !isBrowser;
	}
	constructor(props) {
		const { name, source, url } = props;
		assert$4(source || url);
		this.name = name;
		this.source = source;
		this.url = url;
		this.onMessage = NOOP;
		this.onError = (error) => console.log(error);
		this.worker = isBrowser ? this._createBrowserWorker() : this._createNodeWorker();
	}
	/**
	* Terminate this worker thread
	* @note Can free up significant memory
	*/
	destroy() {
		this.onMessage = NOOP;
		this.onError = NOOP;
		this.worker.terminate();
		this.terminated = true;
	}
	get isRunning() {
		return Boolean(this.onMessage);
	}
	/**
	* Send a message to this worker thread
	* @param data any data structure, ideally consisting mostly of transferrable objects
	* @param transferList If not supplied, calculated automatically by traversing data
	*/
	postMessage(data, transferList) {
		transferList = transferList || getTransferList(data);
		this.worker.postMessage(data, transferList);
	}
	/**
	* Generate a standard Error from an ErrorEvent
	* @param event
	*/
	_getErrorFromErrorEvent(event) {
		let message = "Failed to load ";
		message += `worker ${this.name} from ${this.url}. `;
		if (event.message) message += `${event.message} in `;
		if (event.lineno) message += `:${event.lineno}:${event.colno}`;
		return new Error(message);
	}
	/**
	* Creates a worker thread on the browser
	*/
	_createBrowserWorker() {
		this._loadableURL = getLoadableWorkerURL({
			source: this.source,
			url: this.url
		});
		const worker = new Worker(this._loadableURL, { name: this.name });
		worker.onmessage = (event) => {
			if (!event.data) this.onError(/* @__PURE__ */ new Error("No data received"));
			else this.onMessage(event.data);
		};
		worker.onerror = (error) => {
			this.onError(this._getErrorFromErrorEvent(error));
			this.terminated = true;
		};
		worker.onmessageerror = (event) => console.error(event);
		return worker;
	}
	/**
	* Creates a worker thread in node.js
	* @todo https://nodejs.org/api/async_hooks.html#async-resource-worker-pool
	*/
	_createNodeWorker() {
		let worker;
		if (this.url) worker = new NodeWorker(this.url.includes(":/") || this.url.startsWith("/") ? this.url : `./${this.url}`, {
			eval: false,
			type: this.url.endsWith(".ts") || this.url.endsWith(".mjs") ? "module" : "commonjs"
		});
		else if (this.source) worker = new NodeWorker(this.source, { eval: true });
		else throw new Error("no worker");
		worker.on("message", (data) => {
			this.onMessage(data);
		});
		worker.on("error", (error) => {
			this.onError(error);
		});
		worker.on("exit", (code) => {});
		return worker;
	}
};
//#endregion
//#region node_modules/@loaders.gl/worker-utils/dist/lib/worker-farm/worker-pool.js
/**
* Process multiple data messages with small pool of identical workers
*/
var WorkerPool = class {
	name = "unnamed";
	source;
	url;
	maxConcurrency = 1;
	maxMobileConcurrency = 1;
	onDebug = () => {};
	reuseWorkers = true;
	props = {};
	jobQueue = [];
	idleQueue = [];
	count = 0;
	isDestroyed = false;
	/** Checks if workers are supported on this platform */
	static isSupported() {
		return WorkerThread.isSupported();
	}
	/**
	* @param processor - worker function
	* @param maxConcurrency - max count of workers
	*/
	constructor(props) {
		this.source = props.source;
		this.url = props.url;
		this.setProps(props);
	}
	/**
	* Terminates all workers in the pool
	* @note Can free up significant memory
	*/
	destroy() {
		this.idleQueue.forEach((worker) => worker.destroy());
		this.isDestroyed = true;
	}
	setProps(props) {
		this.props = {
			...this.props,
			...props
		};
		if (props.name !== void 0) this.name = props.name;
		if (props.maxConcurrency !== void 0) this.maxConcurrency = props.maxConcurrency;
		if (props.maxMobileConcurrency !== void 0) this.maxMobileConcurrency = props.maxMobileConcurrency;
		if (props.reuseWorkers !== void 0) this.reuseWorkers = props.reuseWorkers;
		if (props.onDebug !== void 0) this.onDebug = props.onDebug;
	}
	async startJob(name, onMessage = (job, type, data) => job.done(data), onError = (job, error) => job.error(error)) {
		const startPromise = new Promise((onStart) => {
			this.jobQueue.push({
				name,
				onMessage,
				onError,
				onStart
			});
			return this;
		});
		this._startQueuedJob();
		return await startPromise;
	}
	/**
	* Starts first queued job if worker is available or can be created
	* Called when job is started and whenever a worker returns to the idleQueue
	*/
	async _startQueuedJob() {
		if (!this.jobQueue.length) return;
		const workerThread = this._getAvailableWorker();
		if (!workerThread) return;
		const queuedJob = this.jobQueue.shift();
		if (queuedJob) {
			this.onDebug({
				message: "Starting job",
				name: queuedJob.name,
				workerThread,
				backlog: this.jobQueue.length
			});
			const job = new WorkerJob(queuedJob.name, workerThread);
			workerThread.onMessage = (data) => queuedJob.onMessage(job, data.type, data.payload);
			workerThread.onError = (error) => queuedJob.onError(job, error);
			queuedJob.onStart(job);
			try {
				await job.result;
			} catch (error) {
				console.error(`Worker exception: ${error}`);
			} finally {
				this.returnWorkerToQueue(workerThread);
			}
		}
	}
	/**
	* Returns a worker to the idle queue
	* Destroys the worker if
	*  - pool is destroyed
	*  - if this pool doesn't reuse workers
	*  - if maxConcurrency has been lowered
	* @param worker
	*/
	returnWorkerToQueue(worker) {
		if (!isBrowser || this.isDestroyed || !this.reuseWorkers || this.count > this._getMaxConcurrency()) {
			worker.destroy();
			this.count--;
		} else this.idleQueue.push(worker);
		if (!this.isDestroyed) this._startQueuedJob();
	}
	/**
	* Returns idle worker or creates new worker if maxConcurrency has not been reached
	*/
	_getAvailableWorker() {
		if (this.idleQueue.length > 0) return this.idleQueue.shift() || null;
		if (this.count < this._getMaxConcurrency()) {
			this.count++;
			return new WorkerThread({
				name: `${this.name.toLowerCase()} (#${this.count} of ${this.maxConcurrency})`,
				source: this.source,
				url: this.url
			});
		}
		return null;
	}
	_getMaxConcurrency() {
		return isMobile ? this.maxMobileConcurrency : this.maxConcurrency;
	}
};
//#endregion
//#region node_modules/@loaders.gl/worker-utils/dist/lib/worker-farm/worker-farm.js
var DEFAULT_PROPS = {
	maxConcurrency: 3,
	maxMobileConcurrency: 1,
	reuseWorkers: true,
	onDebug: () => {}
};
/**
* Process multiple jobs with a "farm" of different workers in worker pools.
*/
var WorkerFarm = class WorkerFarm {
	props;
	workerPools = /* @__PURE__ */ new Map();
	static _workerFarm;
	/** Checks if workers are supported on this platform */
	static isSupported() {
		return WorkerThread.isSupported();
	}
	/** Get the singleton instance of the global worker farm */
	static getWorkerFarm(props = {}) {
		WorkerFarm._workerFarm = WorkerFarm._workerFarm || new WorkerFarm({});
		WorkerFarm._workerFarm.setProps(props);
		return WorkerFarm._workerFarm;
	}
	/** get global instance with WorkerFarm.getWorkerFarm() */
	constructor(props) {
		this.props = { ...DEFAULT_PROPS };
		this.setProps(props);
		/** @type Map<string, WorkerPool>} */
		this.workerPools = /* @__PURE__ */ new Map();
	}
	/**
	* Terminate all workers in the farm
	* @note Can free up significant memory
	*/
	destroy() {
		for (const workerPool of this.workerPools.values()) workerPool.destroy();
		this.workerPools = /* @__PURE__ */ new Map();
	}
	/**
	* Set props used when initializing worker pools
	* @param props
	*/
	setProps(props) {
		this.props = {
			...this.props,
			...props
		};
		for (const workerPool of this.workerPools.values()) workerPool.setProps(this._getWorkerPoolProps());
	}
	/**
	* Returns a worker pool for the specified worker
	* @param options - only used first time for a specific worker name
	* @param options.name - the name of the worker - used to identify worker pool
	* @param options.url -
	* @param options.source -
	* @example
	*   const job = WorkerFarm.getWorkerFarm().getWorkerPool({name, url}).startJob(...);
	*/
	getWorkerPool(options) {
		const { name, source, url } = options;
		let workerPool = this.workerPools.get(name);
		if (!workerPool) {
			workerPool = new WorkerPool({
				name,
				source,
				url
			});
			workerPool.setProps(this._getWorkerPoolProps());
			this.workerPools.set(name, workerPool);
		}
		return workerPool;
	}
	_getWorkerPoolProps() {
		return {
			maxConcurrency: this.props.maxConcurrency,
			maxMobileConcurrency: this.props.maxMobileConcurrency,
			reuseWorkers: this.props.reuseWorkers,
			onDebug: this.props.onDebug
		};
	}
};
//#endregion
//#region node_modules/@loaders.gl/worker-utils/dist/lib/worker-api/get-worker-url.js
/**
* Generate a worker URL based on worker object and options
* @returns A URL to one of the following:
* - a published worker on unpkg CDN
* - a local test worker
* - a URL provided by the user in options
*/
function getWorkerURL(worker, options = {}) {
	const workerOptions = options[worker.id] || {};
	const workerFile = isBrowser ? `${worker.id}-worker.js` : `${worker.id}-worker-node.js`;
	let url = workerOptions.workerUrl;
	if (!url && worker.id === "compression") url = options.workerUrl;
	if ((options._workerType || options?.core?._workerType) === "test") if (isBrowser) url = `modules/${worker.module}/dist/${workerFile}`;
	else url = `modules/${worker.module}/src/workers/${worker.id}-worker-node.ts`;
	if (!url) {
		let version = worker.version;
		if (version === "latest") version = NPM_TAG;
		const versionTag = version ? `@${version}` : "";
		url = `https://unpkg.com/@loaders.gl/${worker.module}${versionTag}/dist/${workerFile}`;
	}
	assert$4(url);
	return url;
}
//#endregion
//#region node_modules/@loaders.gl/worker-utils/dist/lib/worker-api/validate-worker-version.js
/**
* Check if worker is compatible with this library version
* @param worker
* @param libVersion
* @returns `true` if the two versions are compatible
*/
function validateWorkerVersion(worker, coreVersion = VERSION) {
	assert$4(worker, "no worker provided");
	const workerVersion = worker.version;
	if (!coreVersion || !workerVersion) return false;
	return true;
}
//#endregion
//#region node_modules/@loaders.gl/loader-utils/dist/lib/worker-loader-utils/parse-with-worker.js
/**
* Determines if a loader can parse with worker
* @param loader
* @param options
*/
function canParseWithWorker(loader, options) {
	if (!WorkerFarm.isSupported()) return false;
	const nodeWorkers = options?._nodeWorkers ?? options?.core?._nodeWorkers;
	if (!isBrowser && !nodeWorkers) return false;
	const useWorkers = options?.worker ?? options?.core?.worker;
	return Boolean(loader.worker && useWorkers);
}
/**
* this function expects that the worker function sends certain messages,
* this can be automated if the worker is wrapper by a call to createLoaderWorker in @loaders.gl/loader-utils.
*/
async function parseWithWorker(loader, data, options, context, parseOnMainThread) {
	const name = loader.id;
	const url = getWorkerURL(loader, options);
	const workerPool = WorkerFarm.getWorkerFarm(options?.core).getWorkerPool({
		name,
		url
	});
	options = JSON.parse(JSON.stringify(options));
	context = JSON.parse(JSON.stringify(context || {}));
	const job = await workerPool.startJob("process-on-worker", onMessage.bind(null, parseOnMainThread));
	job.postMessage("process", {
		input: data,
		options,
		context
	});
	return await (await job.result).result;
}
/**
* Handle worker's responses to the main thread
* @param job
* @param type
* @param payload
*/
async function onMessage(parseOnMainThread, job, type, payload) {
	switch (type) {
		case "done":
			job.done(payload);
			break;
		case "error":
			job.error(new Error(payload.error));
			break;
		case "process":
			const { id, input, options } = payload;
			try {
				const result = await parseOnMainThread(input, options);
				job.postMessage("done", {
					id,
					result
				});
			} catch (error) {
				const message = error instanceof Error ? error.message : "unknown error";
				job.postMessage("error", {
					id,
					error: message
				});
			}
			break;
		default: console.warn(`parse-with-worker unknown message ${type}`);
	}
}
//#endregion
//#region node_modules/@loaders.gl/loader-utils/dist/lib/binary-utils/array-buffer-utils.js
/**
* compare two binary arrays for equality
* @param a
* @param b
* @param byteLength
*/
function compareArrayBuffers(arrayBuffer1, arrayBuffer2, byteLength) {
	byteLength = byteLength || arrayBuffer1.byteLength;
	if (arrayBuffer1.byteLength < byteLength || arrayBuffer2.byteLength < byteLength) return false;
	const array1 = new Uint8Array(arrayBuffer1);
	const array2 = new Uint8Array(arrayBuffer2);
	for (let i = 0; i < array1.length; ++i) if (array1[i] !== array2[i]) return false;
	return true;
}
/**
* Concatenate a sequence of ArrayBuffers from arguments
* @return A concatenated ArrayBuffer
*/
function concatenateArrayBuffers(...sources) {
	return concatenateArrayBuffersFromArray(sources);
}
/**
* Concatenate a sequence of ArrayBuffers from array
* @return A concatenated ArrayBuffer
*/
function concatenateArrayBuffersFromArray(sources) {
	const sourceArrays = sources.map((source2) => source2 instanceof ArrayBuffer ? new Uint8Array(source2) : source2);
	const byteLength = sourceArrays.reduce((length, typedArray) => length + typedArray.byteLength, 0);
	const result = new Uint8Array(byteLength);
	let offset = 0;
	for (const sourceArray of sourceArrays) {
		result.set(sourceArray, offset);
		offset += sourceArray.byteLength;
	}
	return result.buffer;
}
//#endregion
//#region node_modules/@loaders.gl/loader-utils/dist/lib/iterators/async-iteration.js
/**
* Concatenates all binary chunks yielded by an async or sync iterator.
* Supports `ArrayBuffer`, typed array views, and `ArrayBufferLike` sources (e.g. `SharedArrayBuffer`).
* This allows atomic parsers to operate on iterator inputs by materializing them into a single buffer.
*/
async function concatenateArrayBuffersAsync(asyncIterator) {
	const arrayBuffers = [];
	for await (const chunk of asyncIterator) arrayBuffers.push(copyToArrayBuffer$1(chunk));
	return concatenateArrayBuffers(...arrayBuffers);
}
function copyToArrayBuffer$1(chunk) {
	if (chunk instanceof ArrayBuffer) return chunk;
	if (ArrayBuffer.isView(chunk)) {
		const { buffer, byteOffset, byteLength } = chunk;
		return copyFromBuffer(buffer, byteOffset, byteLength);
	}
	return copyFromBuffer(chunk);
}
function copyFromBuffer(buffer, byteOffset = 0, byteLength = buffer.byteLength - byteOffset) {
	const view = new Uint8Array(buffer, byteOffset, byteLength);
	const copy = new Uint8Array(view.length);
	copy.set(view);
	return copy.buffer;
}
//#endregion
//#region node_modules/@probe.gl/stats/dist/utils/hi-res-timestamp.js
function getHiResTimestamp() {
	let timestamp;
	if (typeof window !== "undefined" && window.performance) timestamp = window.performance.now();
	else if (typeof process !== "undefined" && process.hrtime) {
		const timeParts = process.hrtime();
		timestamp = timeParts[0] * 1e3 + timeParts[1] / 1e6;
	} else timestamp = Date.now();
	return timestamp;
}
//#endregion
//#region node_modules/@probe.gl/stats/dist/lib/stat.js
var Stat = class {
	constructor(name, type) {
		this.sampleSize = 1;
		this.time = 0;
		this.count = 0;
		this.samples = 0;
		this.lastTiming = 0;
		this.lastSampleTime = 0;
		this.lastSampleCount = 0;
		this._count = 0;
		this._time = 0;
		this._samples = 0;
		this._startTime = 0;
		this._timerPending = false;
		this.name = name;
		this.type = type;
		this.reset();
	}
	reset() {
		this.time = 0;
		this.count = 0;
		this.samples = 0;
		this.lastTiming = 0;
		this.lastSampleTime = 0;
		this.lastSampleCount = 0;
		this._count = 0;
		this._time = 0;
		this._samples = 0;
		this._startTime = 0;
		this._timerPending = false;
		return this;
	}
	setSampleSize(samples) {
		this.sampleSize = samples;
		return this;
	}
	/** Call to increment count (+1) */
	incrementCount() {
		this.addCount(1);
		return this;
	}
	/** Call to decrement count (-1) */
	decrementCount() {
		this.subtractCount(1);
		return this;
	}
	/** Increase count */
	addCount(value) {
		this._count += value;
		this._samples++;
		this._checkSampling();
		return this;
	}
	/** Decrease count */
	subtractCount(value) {
		this._count -= value;
		this._samples++;
		this._checkSampling();
		return this;
	}
	/** Add an arbitrary timing and bump the count */
	addTime(time) {
		this._time += time;
		this.lastTiming = time;
		this._samples++;
		this._checkSampling();
		return this;
	}
	/** Start a timer */
	timeStart() {
		this._startTime = getHiResTimestamp();
		this._timerPending = true;
		return this;
	}
	/** End a timer. Adds to time and bumps the timing count. */
	timeEnd() {
		if (!this._timerPending) return this;
		this.addTime(getHiResTimestamp() - this._startTime);
		this._timerPending = false;
		this._checkSampling();
		return this;
	}
	getSampleAverageCount() {
		return this.sampleSize > 0 ? this.lastSampleCount / this.sampleSize : 0;
	}
	/** Calculate average time / count for the previous window */
	getSampleAverageTime() {
		return this.sampleSize > 0 ? this.lastSampleTime / this.sampleSize : 0;
	}
	/** Calculate counts per second for the previous window */
	getSampleHz() {
		return this.lastSampleTime > 0 ? this.sampleSize / (this.lastSampleTime / 1e3) : 0;
	}
	getAverageCount() {
		return this.samples > 0 ? this.count / this.samples : 0;
	}
	/** Calculate average time / count */
	getAverageTime() {
		return this.samples > 0 ? this.time / this.samples : 0;
	}
	/** Calculate counts per second */
	getHz() {
		return this.time > 0 ? this.samples / (this.time / 1e3) : 0;
	}
	_checkSampling() {
		if (this._samples === this.sampleSize) {
			this.lastSampleTime = this._time;
			this.lastSampleCount = this._count;
			this.count += this._count;
			this.time += this._time;
			this.samples += this._samples;
			this._time = 0;
			this._count = 0;
			this._samples = 0;
		}
	}
};
//#endregion
//#region node_modules/@probe.gl/stats/dist/lib/stats.js
/** A "bag" of `Stat` objects, can be visualized using `StatsWidget` */
var Stats = class {
	constructor(options) {
		this.stats = {};
		this.id = options.id;
		this.stats = {};
		this._initializeStats(options.stats);
		Object.seal(this);
	}
	/** Acquire a stat. Create if it doesn't exist. */
	get(name, type = "count") {
		return this._getOrCreate({
			name,
			type
		});
	}
	get size() {
		return Object.keys(this.stats).length;
	}
	/** Reset all stats */
	reset() {
		for (const stat of Object.values(this.stats)) stat.reset();
		return this;
	}
	forEach(fn) {
		for (const stat of Object.values(this.stats)) fn(stat);
	}
	getTable() {
		const table = {};
		this.forEach((stat) => {
			table[stat.name] = {
				time: stat.time || 0,
				count: stat.count || 0,
				average: stat.getAverageTime() || 0,
				hz: stat.getHz() || 0
			};
		});
		return table;
	}
	_initializeStats(stats = []) {
		stats.forEach((stat) => this._getOrCreate(stat));
	}
	_getOrCreate(stat) {
		const { name, type } = stat;
		let result = this.stats[name];
		if (!result) {
			if (stat instanceof Stat) result = stat;
			else result = new Stat(name, type);
			this.stats[name] = result;
		}
		return result;
	}
};
//#endregion
//#region node_modules/@loaders.gl/loader-utils/dist/lib/path-utils/file-aliases.js
var pathPrefix = "";
var fileAliases = {};
/**
* Resolves aliases and adds path-prefix to paths
*/
function resolvePath(filename) {
	for (const alias in fileAliases) if (filename.startsWith(alias)) {
		const replacement = fileAliases[alias];
		filename = filename.replace(alias, replacement);
	}
	if (!filename.startsWith("http://") && !filename.startsWith("https://")) filename = `${pathPrefix}${filename}`;
	return filename;
}
//#endregion
//#region node_modules/@loaders.gl/loader-utils/dist/lib/node/buffer.browser.js
/**
* Convert Buffer to ArrayBuffer
* Converts Node.js `Buffer` to `ArrayBuffer` (without triggering bundler to include Buffer polyfill on browser)
* @todo better data type
*/
function toArrayBuffer$1(buffer) {
	return buffer;
}
//#endregion
//#region node_modules/@loaders.gl/loader-utils/dist/lib/binary-utils/memory-conversion-utils.js
/**
* Check for Node.js `Buffer` (without triggering bundler to include Buffer polyfill on browser)
*/
function isBuffer(value) {
	return value && typeof value === "object" && value.isBuffer;
}
/**
* Convert an object to an array buffer. Handles SharedArrayBuffers.
*/
function toArrayBuffer(data) {
	if (isBuffer(data)) return toArrayBuffer$1(data);
	if (data instanceof ArrayBuffer) return data;
	if (isSharedArrayBuffer(data)) return copyToArrayBuffer(data);
	if (ArrayBuffer.isView(data)) {
		const buffer = data.buffer;
		if (data.byteOffset === 0 && data.byteLength === data.buffer.byteLength) return buffer;
		return buffer.slice(data.byteOffset, data.byteOffset + data.byteLength);
	}
	if (typeof data === "string") {
		const text = data;
		return new TextEncoder().encode(text).buffer;
	}
	if (data && typeof data === "object" && data._toArrayBuffer) return data._toArrayBuffer();
	throw new Error("toArrayBuffer");
}
/** Ensure that SharedArrayBuffers are copied into ArrayBuffers */
function ensureArrayBuffer(bufferSource) {
	if (bufferSource instanceof ArrayBuffer) return bufferSource;
	if (isSharedArrayBuffer(bufferSource)) return copyToArrayBuffer(bufferSource);
	const { buffer, byteOffset, byteLength } = bufferSource;
	if (buffer instanceof ArrayBuffer && byteOffset === 0 && byteLength === buffer.byteLength) return buffer;
	return copyToArrayBuffer(buffer, byteOffset, byteLength);
}
/** Copies an ArrayBuffer or a section of an ArrayBuffer to a new ArrayBuffer, handles SharedArrayBuffers */
function copyToArrayBuffer(buffer, byteOffset = 0, byteLength = buffer.byteLength - byteOffset) {
	const view = new Uint8Array(buffer, byteOffset, byteLength);
	const copy = new Uint8Array(view.length);
	copy.set(view);
	return copy.buffer;
}
/** Convert an object to an ArrayBufferView, handles SharedArrayBuffers */
function toArrayBufferView(data) {
	if (ArrayBuffer.isView(data)) return data;
	return new Uint8Array(data);
}
//#endregion
//#region node_modules/@loaders.gl/loader-utils/dist/lib/path-utils/path.js
/**
* Replacement for Node.js path.filename
* @param url
*/
function filename(url) {
	const slashIndex = url ? url.lastIndexOf("/") : -1;
	return slashIndex >= 0 ? url.substr(slashIndex + 1) : url;
}
/**
* Replacement for Node.js path.dirname
* @param url
*/
function dirname(url) {
	const slashIndex = url ? url.lastIndexOf("/") : -1;
	return slashIndex >= 0 ? url.substr(0, slashIndex) : "";
}
//#endregion
//#region node_modules/@loaders.gl/core/dist/lib/fetch/fetch-error.js
var FetchError = class extends Error {
	constructor(message, info) {
		super(message);
		this.reason = info.reason;
		this.url = info.url;
		this.response = info.response;
	}
	/** A best effort reason for why the fetch failed */
	reason;
	/** The URL that failed to load. Empty string if not available. */
	url;
	/** The Response object, if any. */
	response;
};
//#endregion
//#region node_modules/@loaders.gl/core/dist/lib/utils/mime-type-utils.js
var DATA_URL_PATTERN = /^data:([-\w.]+\/[-\w.+]+)(;|,)/;
var MIME_TYPE_PATTERN = /^([-\w.]+\/[-\w.+]+)/;
/**
* Compare two MIME types, case insensitively etc.
* @param mimeType1
* @param mimeType2
* @returns true if the MIME types are equivalent
* @see https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types#structure_of_a_mime_type
*/
function compareMIMETypes(mimeType1, mimeType2) {
	if (mimeType1.toLowerCase() === mimeType2.toLowerCase()) return true;
	return false;
}
/**
* Remove extra data like `charset` from MIME types
* @param mimeString
* @returns A clean MIME type, or an empty string
*
* @todo - handle more advanced MIMETYpes, multiple types
* @todo - extract charset etc
*/
function parseMIMEType(mimeString) {
	const matches = MIME_TYPE_PATTERN.exec(mimeString);
	if (matches) return matches[1];
	return mimeString;
}
/**
* Extract MIME type from data URL
*
* @param mimeString
* @returns A clean MIME type, or an empty string
*
* @todo - handle more advanced MIMETYpes, multiple types
* @todo - extract charset etc
*/
function parseMIMETypeFromURL(url) {
	const matches = DATA_URL_PATTERN.exec(url);
	if (matches) return matches[1];
	return "";
}
//#endregion
//#region node_modules/@loaders.gl/core/dist/lib/utils/url-utils.js
var QUERY_STRING_PATTERN = /\?.*/;
function extractQueryString(url) {
	const matches = url.match(QUERY_STRING_PATTERN);
	return matches && matches[0];
}
function stripQueryString(url) {
	return url.replace(QUERY_STRING_PATTERN, "");
}
function shortenUrlForDisplay(url) {
	if (url.length < 50) return url;
	const urlEnd = url.slice(url.length - 15);
	return `${url.substr(0, 32)}...${urlEnd}`;
}
//#endregion
//#region node_modules/@loaders.gl/core/dist/lib/utils/resource-utils.js
/**
* Returns the URL associated with this resource.
* The returned value may include a query string and need further processing.
* If it cannot determine url, the corresponding value will be an empty string
*
* @todo string parameters are assumed to be URLs
*/
function getResourceUrl(resource) {
	if (isResponse(resource)) return resource.url;
	if (isBlob(resource)) return ("name" in resource ? resource.name : "") || "";
	if (typeof resource === "string") return resource;
	return "";
}
/**
* Returns the URL associated with this resource.
* The returned value may include a query string and need further processing.
* If it cannot determine url, the corresponding value will be an empty string
*
* @todo string parameters are assumed to be URLs
*/
function getResourceMIMEType(resource) {
	if (isResponse(resource)) {
		const contentTypeHeader = resource.headers.get("content-type") || "";
		const noQueryUrl = stripQueryString(resource.url);
		return parseMIMEType(contentTypeHeader) || parseMIMETypeFromURL(noQueryUrl);
	}
	if (isBlob(resource)) return resource.type || "";
	if (typeof resource === "string") return parseMIMETypeFromURL(resource);
	return "";
}
/**
* Returns (approximate) content length for a resource if it can be determined.
* Returns -1 if content length cannot be determined.
* @param resource

* @note string parameters are NOT assumed to be URLs
*/
function getResourceContentLength(resource) {
	if (isResponse(resource)) return resource.headers["content-length"] || -1;
	if (isBlob(resource)) return resource.size;
	if (typeof resource === "string") return resource.length;
	if (resource instanceof ArrayBuffer) return resource.byteLength;
	if (ArrayBuffer.isView(resource)) return resource.byteLength;
	return -1;
}
//#endregion
//#region node_modules/@loaders.gl/core/dist/lib/utils/response-utils.js
/**
* Returns a Response object
* Adds content-length header when possible
*
* @param resource
*/
async function makeResponse(resource) {
	if (isResponse(resource)) return resource;
	const headers = {};
	const contentLength = getResourceContentLength(resource);
	if (contentLength >= 0) headers["content-length"] = String(contentLength);
	const url = getResourceUrl(resource);
	const type = getResourceMIMEType(resource);
	if (type) headers["content-type"] = type;
	const initialDataUrl = await getInitialDataUrl(resource);
	if (initialDataUrl) headers["x-first-bytes"] = initialDataUrl;
	if (typeof resource === "string") resource = new TextEncoder().encode(resource);
	const response = new Response(resource, { headers });
	Object.defineProperty(response, "url", { value: url });
	return response;
}
/**
* Checks response status (async) and throws a helpful error message if status is not OK.
* @param response
*/
async function checkResponse(response) {
	if (!response.ok) throw await getResponseError(response);
}
async function getResponseError(response) {
	const shortUrl = shortenUrlForDisplay(response.url);
	let message = `Failed to fetch resource (${response.status}) ${response.statusText}: ${shortUrl}`;
	message = message.length > 100 ? `${message.slice(0, 100)}...` : message;
	const info = {
		reason: response.statusText,
		url: response.url,
		response
	};
	try {
		const contentType = response.headers.get("Content-Type");
		info.reason = !response.bodyUsed && contentType?.includes("application/json") ? await response.json() : await response.text();
	} catch (error) {}
	return new FetchError(message, info);
}
async function getInitialDataUrl(resource) {
	const INITIAL_DATA_LENGTH = 5;
	if (typeof resource === "string") return `data:,${resource.slice(0, INITIAL_DATA_LENGTH)}`;
	if (resource instanceof Blob) {
		const blobSlice = resource.slice(0, 5);
		return await new Promise((resolve) => {
			const reader = new FileReader();
			reader.onload = (event) => resolve(event?.target?.result);
			reader.readAsDataURL(blobSlice);
		});
	}
	if (resource instanceof ArrayBuffer) return `data:base64,${arrayBufferToBase64(resource.slice(0, INITIAL_DATA_LENGTH))}`;
	return null;
}
function arrayBufferToBase64(buffer) {
	let binary = "";
	const bytes = new Uint8Array(buffer);
	for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
	return btoa(binary);
}
//#endregion
//#region node_modules/@loaders.gl/core/dist/lib/fetch/fetch-file.js
function isNodePath(url) {
	return !isRequestURL(url) && !isDataURL(url);
}
function isRequestURL(url) {
	return url.startsWith("http:") || url.startsWith("https:");
}
function isDataURL(url) {
	return url.startsWith("data:");
}
/**
* fetch API compatible function
* - Supports fetching from Node.js local file system paths
* - Respects pathPrefix and file aliases
*/
async function fetchFile(urlOrData, fetchOptions) {
	if (typeof urlOrData === "string") {
		const url = resolvePath(urlOrData);
		if (isNodePath(url)) {
			if (globalThis.loaders?.fetchNode) return globalThis.loaders?.fetchNode(url, fetchOptions);
		}
		return await fetch(url, fetchOptions);
	}
	return await makeResponse(urlOrData);
}
//#endregion
//#region node_modules/@loaders.gl/core/dist/lib/loader-utils/loggers.js
var probeLog = new ProbeLog({ id: "loaders.gl" });
var NullLog = class {
	log() {
		return () => {};
	}
	info() {
		return () => {};
	}
	warn() {
		return () => {};
	}
	error() {
		return () => {};
	}
};
var ConsoleLog = class {
	console;
	constructor() {
		this.console = console;
	}
	log(...args) {
		return this.console.log.bind(this.console, ...args);
	}
	info(...args) {
		return this.console.info.bind(this.console, ...args);
	}
	warn(...args) {
		return this.console.warn.bind(this.console, ...args);
	}
	error(...args) {
		return this.console.error.bind(this.console, ...args);
	}
};
//#endregion
//#region node_modules/@loaders.gl/core/dist/lib/loader-utils/option-defaults.js
var DEFAULT_LOADER_OPTIONS = { core: {
	baseUrl: void 0,
	fetch: null,
	mimeType: void 0,
	fallbackMimeType: void 0,
	ignoreRegisteredLoaders: void 0,
	nothrow: false,
	log: new ConsoleLog(),
	useLocalLibraries: false,
	CDN: "https://unpkg.com/@loaders.gl",
	worker: true,
	maxConcurrency: 3,
	maxMobileConcurrency: 1,
	reuseWorkers: isBrowser$2,
	_nodeWorkers: false,
	_workerType: "",
	limit: 0,
	_limitMB: 0,
	batchSize: "auto",
	batchDebounceMs: 0,
	metadata: false,
	transforms: []
} };
var REMOVED_LOADER_OPTIONS = {
	baseUri: "core.baseUrl",
	fetch: "core.fetch",
	mimeType: "core.mimeType",
	fallbackMimeType: "core.fallbackMimeType",
	ignoreRegisteredLoaders: "core.ignoreRegisteredLoaders",
	nothrow: "core.nothrow",
	log: "core.log",
	useLocalLibraries: "core.useLocalLibraries",
	CDN: "core.CDN",
	worker: "core.worker",
	maxConcurrency: "core.maxConcurrency",
	maxMobileConcurrency: "core.maxMobileConcurrency",
	reuseWorkers: "core.reuseWorkers",
	_nodeWorkers: "core.nodeWorkers",
	_workerType: "core._workerType",
	_worker: "core._workerType",
	limit: "core.limit",
	_limitMB: "core._limitMB",
	batchSize: "core.batchSize",
	batchDebounceMs: "core.batchDebounceMs",
	metadata: "core.metadata",
	transforms: "core.transforms",
	throws: "nothrow",
	dataType: "(no longer used)",
	uri: "core.baseUrl",
	method: "core.fetch.method",
	headers: "core.fetch.headers",
	body: "core.fetch.body",
	mode: "core.fetch.mode",
	credentials: "core.fetch.credentials",
	cache: "core.fetch.cache",
	redirect: "core.fetch.redirect",
	referrer: "core.fetch.referrer",
	referrerPolicy: "core.fetch.referrerPolicy",
	integrity: "core.fetch.integrity",
	keepalive: "core.fetch.keepalive",
	signal: "core.fetch.signal"
};
//#endregion
//#region node_modules/@loaders.gl/core/dist/lib/loader-utils/option-utils.js
var CORE_LOADER_OPTION_KEYS = [
	"baseUrl",
	"fetch",
	"mimeType",
	"fallbackMimeType",
	"ignoreRegisteredLoaders",
	"nothrow",
	"log",
	"useLocalLibraries",
	"CDN",
	"worker",
	"maxConcurrency",
	"maxMobileConcurrency",
	"reuseWorkers",
	"_nodeWorkers",
	"_workerType",
	"limit",
	"_limitMB",
	"batchSize",
	"batchDebounceMs",
	"metadata",
	"transforms"
];
/**
* Helper for safely accessing global loaders.gl variables
* Wraps initialization of global variable in function to defeat overly aggressive tree-shakers
*/
function getGlobalLoaderState() {
	globalThis.loaders = globalThis.loaders || {};
	const { loaders } = globalThis;
	if (!loaders._state) loaders._state = {};
	return loaders._state;
}
/**
* Store global loader options on the global object to increase chances of cross loaders-version interoperability
* NOTE: This use case is not reliable but can help when testing new versions of loaders.gl with existing frameworks
* @returns global loader options merged with default loader options
*/
function getGlobalLoaderOptions() {
	const state = getGlobalLoaderState();
	state.globalOptions = state.globalOptions || {
		...DEFAULT_LOADER_OPTIONS,
		core: { ...DEFAULT_LOADER_OPTIONS.core }
	};
	return normalizeLoaderOptions(state.globalOptions);
}
/**
* Merges options with global opts and loader defaults, also injects baseUrl
* @param options
* @param loader
* @param loaders
* @param url
*/
function normalizeOptions(options, loader, loaders, url) {
	loaders = loaders || [];
	loaders = Array.isArray(loaders) ? loaders : [loaders];
	validateOptions(options, loaders);
	return normalizeLoaderOptions(normalizeOptionsInternal(loader, options, url));
}
/**
* Returns a copy of the provided options with deprecated top-level core fields moved into `core`
* and removed from the top level. This keeps global options from leaking deprecated aliases into
* loader-specific option maps during normalization.
*/
function normalizeLoaderOptions(options) {
	const normalized = cloneLoaderOptions(options);
	moveDeprecatedTopLevelOptionsToCore(normalized);
	for (const key of CORE_LOADER_OPTION_KEYS) if (normalized.core && normalized.core[key] !== void 0) delete normalized[key];
	if (normalized.core && normalized.core._workerType !== void 0) delete normalized._worker;
	return normalized;
}
/**
* Warn for unsupported options
* @param options
* @param loaders
*/
function validateOptions(options, loaders) {
	validateOptionsObject(options, null, DEFAULT_LOADER_OPTIONS, REMOVED_LOADER_OPTIONS, loaders);
	for (const loader of loaders) {
		const idOptions = options && options[loader.id] || {};
		const loaderOptions = loader.options && loader.options[loader.id] || {};
		const deprecatedOptions = loader.deprecatedOptions && loader.deprecatedOptions[loader.id] || {};
		validateOptionsObject(idOptions, loader.id, loaderOptions, deprecatedOptions, loaders);
	}
}
function validateOptionsObject(options, id, defaultOptions, deprecatedOptions, loaders) {
	const loaderName = id || "Top level";
	const prefix = id ? `${id}.` : "";
	for (const key in options) {
		const isSubOptions = !id && isObject(options[key]);
		const isBaseUriOption = key === "baseUri" && !id;
		const isWorkerUrlOption = key === "workerUrl" && id;
		if (!(key in defaultOptions) && !isBaseUriOption && !isWorkerUrlOption) {
			if (key in deprecatedOptions) {
				if (probeLog.level > 0) probeLog.warn(`${loaderName} loader option \'${prefix}${key}\' no longer supported, use \'${deprecatedOptions[key]}\'`)();
			} else if (!isSubOptions) {
				if (probeLog.level > 0) {
					const suggestion = findSimilarOption(key, loaders);
					probeLog.warn(`${loaderName} loader option \'${prefix}${key}\' not recognized. ${suggestion}`)();
				}
			}
		}
	}
}
function findSimilarOption(optionKey, loaders) {
	const lowerCaseOptionKey = optionKey.toLowerCase();
	let bestSuggestion = "";
	for (const loader of loaders) for (const key in loader.options) {
		if (optionKey === key) return `Did you mean \'${loader.id}.${key}\'?`;
		const lowerCaseKey = key.toLowerCase();
		if (lowerCaseOptionKey.startsWith(lowerCaseKey) || lowerCaseKey.startsWith(lowerCaseOptionKey)) bestSuggestion = bestSuggestion || `Did you mean \'${loader.id}.${key}\'?`;
	}
	return bestSuggestion;
}
function normalizeOptionsInternal(loader, options, url) {
	const loaderDefaultOptions = loader.options || {};
	const mergedOptions = { ...loaderDefaultOptions };
	if (loaderDefaultOptions.core) mergedOptions.core = { ...loaderDefaultOptions.core };
	moveDeprecatedTopLevelOptionsToCore(mergedOptions);
	if (mergedOptions.core?.log === null) mergedOptions.core = {
		...mergedOptions.core,
		log: new NullLog()
	};
	mergeNestedFields(mergedOptions, normalizeLoaderOptions(getGlobalLoaderOptions()));
	mergeNestedFields(mergedOptions, normalizeLoaderOptions(options));
	addUrlOptions(mergedOptions, url);
	addDeprecatedTopLevelOptions(mergedOptions);
	return mergedOptions;
}
function mergeNestedFields(mergedOptions, options) {
	for (const key in options) if (key in options) {
		const value = options[key];
		if (isPureObject(value) && isPureObject(mergedOptions[key])) mergedOptions[key] = {
			...mergedOptions[key],
			...options[key]
		};
		else mergedOptions[key] = options[key];
	}
}
/**
* Harvest information from the url
* @deprecated This is mainly there to support loaders that still resolve from options
* TODO - extract extension?
* TODO - extract query parameters?
* TODO - should these be injected on context instead of options?
*/
function addUrlOptions(options, url) {
	if (!url) return;
	if (!(options.core?.baseUrl !== void 0)) {
		options.core ||= {};
		options.core.baseUrl = dirname(stripQueryString(url));
	}
}
function cloneLoaderOptions(options) {
	const clonedOptions = { ...options };
	if (options.core) clonedOptions.core = { ...options.core };
	return clonedOptions;
}
function moveDeprecatedTopLevelOptionsToCore(options) {
	if (options.baseUri !== void 0) {
		options.core ||= {};
		if (options.core.baseUrl === void 0) options.core.baseUrl = options.baseUri;
	}
	for (const key of CORE_LOADER_OPTION_KEYS) if (options[key] !== void 0) {
		const coreRecord = options.core = options.core || {};
		if (coreRecord[key] === void 0) coreRecord[key] = options[key];
	}
	const workerTypeAlias = options._worker;
	if (workerTypeAlias !== void 0) {
		options.core ||= {};
		if (options.core._workerType === void 0) options.core._workerType = workerTypeAlias;
	}
}
function addDeprecatedTopLevelOptions(options) {
	const coreOptions = options.core;
	if (!coreOptions) return;
	for (const key of CORE_LOADER_OPTION_KEYS) if (coreOptions[key] !== void 0) options[key] = coreOptions[key];
}
//#endregion
//#region node_modules/@loaders.gl/core/dist/lib/loader-utils/normalize-loader.js
function isLoaderObject(loader) {
	if (!loader) return false;
	if (Array.isArray(loader)) loader = loader[0];
	return Array.isArray(loader?.extensions);
}
function normalizeLoader(loader) {
	assert$6(loader, "null loader");
	assert$6(isLoaderObject(loader), "invalid loader");
	let options;
	if (Array.isArray(loader)) {
		options = loader[1];
		loader = loader[0];
		loader = {
			...loader,
			options: {
				...loader.options,
				...options
			}
		};
	}
	if (loader?.parseTextSync || loader?.parseText) loader.text = true;
	if (!loader.text) loader.binary = true;
	return loader;
}
//#endregion
//#region node_modules/@loaders.gl/core/dist/lib/api/register-loaders.js
/**
* Store global registered loaders on the global object to increase chances of cross loaders-version interoperability
* This use case is not reliable but can help when testing new versions of loaders.gl with existing frameworks
*/
var getGlobalLoaderRegistry = () => {
	const state = getGlobalLoaderState();
	state.loaderRegistry = state.loaderRegistry || [];
	return state.loaderRegistry;
};
/**
* Register a list of global loaders
* @note Registration erases loader type information.
* @deprecated It is recommended that applications manage loader registration. This function will likely be remove in loaders.gl v5
*/
function registerLoaders(loaders) {
	const loaderRegistry = getGlobalLoaderRegistry();
	loaders = Array.isArray(loaders) ? loaders : [loaders];
	for (const loader of loaders) {
		const normalizedLoader = normalizeLoader(loader);
		if (!loaderRegistry.find((registeredLoader) => normalizedLoader === registeredLoader)) loaderRegistry.unshift(normalizedLoader);
	}
}
/**
* @deprecated It is recommended that applications manage loader registration. This function will likely be remove in loaders.gl v5
*/
function getRegisteredLoaders() {
	return getGlobalLoaderRegistry();
}
//#endregion
//#region node_modules/@loaders.gl/core/dist/lib/api/select-loader.js
var EXT_PATTERN = /\.([^.]+)$/;
/**
* Find a loader that matches file extension and/or initial file content
* Search the loaders array argument for a loader that matches url extension or initial data
* Returns: a normalized loader
* @param data data to assist
* @param loaders
* @param options
* @param context used internally, applications should not provide this parameter
*/
async function selectLoader(data, loaders = [], options, context) {
	if (!validHTTPResponse(data)) return null;
	const normalizedOptions = normalizeLoaderOptions(options || {});
	normalizedOptions.core ||= {};
	if (data instanceof Response && mayContainText(data)) {
		const textLoader = selectLoaderSync(await data.clone().text(), loaders, {
			...normalizedOptions,
			core: {
				...normalizedOptions.core,
				nothrow: true
			}
		}, context);
		if (textLoader) return textLoader;
	}
	let loader = selectLoaderSync(data, loaders, {
		...normalizedOptions,
		core: {
			...normalizedOptions.core,
			nothrow: true
		}
	}, context);
	if (loader) return loader;
	if (isBlob(data)) {
		data = await data.slice(0, 10).arrayBuffer();
		loader = selectLoaderSync(data, loaders, normalizedOptions, context);
	}
	if (!loader && data instanceof Response && mayContainText(data)) loader = selectLoaderSync(await data.clone().text(), loaders, normalizedOptions, context);
	if (!loader && !normalizedOptions.core.nothrow) throw new Error(getNoValidLoaderMessage(data));
	return loader;
}
function mayContainText(response) {
	const mimeType = getResourceMIMEType(response);
	return Boolean(mimeType && (mimeType.startsWith("text/") || mimeType === "application/json" || mimeType.endsWith("+json")));
}
/**
* Find a loader that matches file extension and/or initial file content
* Search the loaders array argument for a loader that matches url extension or initial data
* Returns: a normalized loader
* @param data data to assist
* @param loaders
* @param options
* @param context used internally, applications should not provide this parameter
*/
function selectLoaderSync(data, loaders = [], options, context) {
	if (!validHTTPResponse(data)) return null;
	const normalizedOptions = normalizeLoaderOptions(options || {});
	normalizedOptions.core ||= {};
	if (loaders && !Array.isArray(loaders)) return normalizeLoader(loaders);
	let candidateLoaders = [];
	if (loaders) candidateLoaders = candidateLoaders.concat(loaders);
	if (!normalizedOptions.core.ignoreRegisteredLoaders) candidateLoaders.push(...getRegisteredLoaders());
	normalizeLoaders(candidateLoaders);
	const loader = selectLoaderInternal(data, candidateLoaders, normalizedOptions, context);
	if (!loader && !normalizedOptions.core.nothrow) throw new Error(getNoValidLoaderMessage(data));
	return loader;
}
/** Implements loaders selection logic */
function selectLoaderInternal(data, loaders, options, context) {
	const url = getResourceUrl(data);
	const type = getResourceMIMEType(data);
	const testUrl = stripQueryString(url) || context?.url;
	let loader = null;
	let reason = "";
	if (options?.core?.mimeType) {
		loader = findLoaderByMIMEType(loaders, options?.core?.mimeType);
		reason = `match forced by supplied MIME type ${options?.core?.mimeType}`;
	}
	loader = loader || findLoaderByUrl(loaders, testUrl);
	reason = reason || (loader ? `matched url ${testUrl}` : "");
	loader = loader || findLoaderByMIMEType(loaders, type);
	reason = reason || (loader ? `matched MIME type ${type}` : "");
	loader = loader || findLoaderByInitialBytes(loaders, data);
	reason = reason || (loader ? `matched initial data ${getFirstCharacters(data)}` : "");
	if (options?.core?.fallbackMimeType) {
		loader = loader || findLoaderByMIMEType(loaders, options?.core?.fallbackMimeType);
		reason = reason || (loader ? `matched fallback MIME type ${type}` : "");
	}
	if (reason) log$1.log(1, `selectLoader selected ${loader?.name}: ${reason}.`);
	return loader;
}
/** Check HTTP Response */
function validHTTPResponse(data) {
	if (data instanceof Response) {
		if (data.status === 204) return false;
	}
	return true;
}
/** Generate a helpful message to help explain why loader selection failed. */
function getNoValidLoaderMessage(data) {
	const url = getResourceUrl(data);
	const type = getResourceMIMEType(data);
	let message = "No valid loader found (";
	message += url ? `${filename(url)}, ` : "no url provided, ";
	message += `MIME type: ${type ? `"${type}"` : "not provided"}, `;
	const firstCharacters = data ? getFirstCharacters(data) : "";
	message += firstCharacters ? ` first bytes: "${firstCharacters}"` : "first bytes: not available";
	message += ")";
	return message;
}
function normalizeLoaders(loaders) {
	for (const loader of loaders) normalizeLoader(loader);
}
function findLoaderByUrl(loaders, url) {
	const match = url && EXT_PATTERN.exec(url);
	const extension = match && match[1];
	return extension ? findLoaderByExtension(loaders, extension) : null;
}
function findLoaderByExtension(loaders, extension) {
	extension = extension.toLowerCase();
	for (const loader of loaders) for (const loaderExtension of loader.extensions) if (loaderExtension.toLowerCase() === extension) return loader;
	return null;
}
function findLoaderByMIMEType(loaders, mimeType) {
	for (const loader of loaders) {
		if (loader.mimeTypes?.some((mimeType1) => compareMIMETypes(mimeType, mimeType1))) return loader;
		if (compareMIMETypes(mimeType, `application/x.${loader.id}`)) return loader;
	}
	return null;
}
function findLoaderByInitialBytes(loaders, data) {
	if (!data) return null;
	for (const loader of loaders) if (typeof data === "string") {
		if (testDataAgainstText(data, loader)) return loader;
	} else if (ArrayBuffer.isView(data)) {
		if (testDataAgainstBinary(data.buffer, data.byteOffset, loader)) return loader;
	} else if (data instanceof ArrayBuffer) {
		if (testDataAgainstBinary(data, 0, loader)) return loader;
	}
	return null;
}
function testDataAgainstText(data, loader) {
	if (loader.testText) return loader.testText(data);
	return (Array.isArray(loader.tests) ? loader.tests : [loader.tests]).some((test) => data.startsWith(test));
}
function testDataAgainstBinary(data, byteOffset, loader) {
	return (Array.isArray(loader.tests) ? loader.tests : [loader.tests]).some((test) => testBinary(data, byteOffset, loader, test));
}
function testBinary(data, byteOffset, loader, test) {
	if (isArrayBufferLike(test)) return compareArrayBuffers(test, data, test.byteLength);
	switch (typeof test) {
		case "function": return test(ensureArrayBuffer(data));
		case "string": return test === getMagicString(data, byteOffset, test.length);
		default: return false;
	}
}
function getFirstCharacters(data, length = 5) {
	if (typeof data === "string") return data.slice(0, length);
	else if (ArrayBuffer.isView(data)) return getMagicString(data.buffer, data.byteOffset, length);
	else if (data instanceof ArrayBuffer) return getMagicString(data, 0, length);
	return "";
}
function getMagicString(arrayBuffer, byteOffset, length) {
	if (arrayBuffer.byteLength < byteOffset + length) return "";
	const dataView = new DataView(arrayBuffer);
	let magic = "";
	for (let i = 0; i < length; i++) magic += String.fromCharCode(dataView.getUint8(byteOffset + i));
	return magic;
}
//#endregion
//#region node_modules/@loaders.gl/core/dist/iterators/make-iterator/make-string-iterator.js
var DEFAULT_CHUNK_SIZE$2 = 256 * 1024;
/**
* Returns an iterator that breaks a big string into chunks and yields them one-by-one as ArrayBuffers
* @param blob string to iterate over
* @param options
* @param options.chunkSize
*/
function* makeStringIterator(string, options) {
	const chunkSize = options?.chunkSize || DEFAULT_CHUNK_SIZE$2;
	let offset = 0;
	const textEncoder = new TextEncoder();
	while (offset < string.length) {
		const chunkLength = Math.min(string.length - offset, chunkSize);
		const chunk = string.slice(offset, offset + chunkLength);
		offset += chunkLength;
		yield ensureArrayBuffer(textEncoder.encode(chunk));
	}
}
//#endregion
//#region node_modules/@loaders.gl/core/dist/iterators/make-iterator/make-array-buffer-iterator.js
var DEFAULT_CHUNK_SIZE$1 = 256 * 1024;
/**
* Returns an iterator that breaks a big ArrayBuffer into chunks and yields them one-by-one
* @param blob ArrayBuffer to iterate over
* @param options
* @param options.chunkSize
*/
function* makeArrayBufferIterator(arrayBuffer, options = {}) {
	const { chunkSize = DEFAULT_CHUNK_SIZE$1 } = options;
	let byteOffset = 0;
	while (byteOffset < arrayBuffer.byteLength) {
		const chunkByteLength = Math.min(arrayBuffer.byteLength - byteOffset, chunkSize);
		const chunk = new ArrayBuffer(chunkByteLength);
		const sourceArray = new Uint8Array(arrayBuffer, byteOffset, chunkByteLength);
		new Uint8Array(chunk).set(sourceArray);
		byteOffset += chunkByteLength;
		yield chunk;
	}
}
//#endregion
//#region node_modules/@loaders.gl/core/dist/iterators/make-iterator/make-blob-iterator.js
var DEFAULT_CHUNK_SIZE = 1024 * 1024;
/**
* Returns an iterator that breaks a big Blob into chunks and yields them one-by-one
* @param blob Blob or File object
* @param options
* @param options.chunkSize
*/
async function* makeBlobIterator(blob, options) {
	const chunkSize = options?.chunkSize || DEFAULT_CHUNK_SIZE;
	let offset = 0;
	while (offset < blob.size) {
		const end = offset + chunkSize;
		const chunk = await blob.slice(offset, end).arrayBuffer();
		offset = end;
		yield chunk;
	}
}
//#endregion
//#region node_modules/@loaders.gl/core/dist/iterators/make-iterator/make-stream-iterator.js
/**
* Returns an async iterable that reads from a stream (works in both Node.js and browsers)
* @param stream stream to iterator over
*/
function makeStreamIterator(stream, options) {
	return isBrowser$2 ? makeBrowserStreamIterator(stream, options) : makeNodeStreamIterator(stream, options);
}
/**
* Returns an async iterable that reads from a DOM (browser) stream
* @param stream stream to iterate from
* @see https://jakearchibald.com/2017/async-iterators-and-generators/#making-streams-iterate
*/
async function* makeBrowserStreamIterator(stream, options) {
	const reader = stream.getReader();
	let nextBatchPromise;
	try {
		while (true) {
			const currentBatchPromise = nextBatchPromise || reader.read();
			if (options?._streamReadAhead) nextBatchPromise = reader.read();
			const { done, value } = await currentBatchPromise;
			if (done) return;
			yield toArrayBuffer(value);
		}
	} catch (error) {
		reader.releaseLock();
	}
}
/**
* Returns an async iterable that reads from a DOM (browser) stream
* @param stream stream to iterate from
* @note Requires Node.js >= 10
*/
async function* makeNodeStreamIterator(stream, options) {
	for await (const chunk of stream) yield toArrayBuffer(chunk);
}
//#endregion
//#region node_modules/@loaders.gl/core/dist/iterators/make-iterator/make-iterator.js
/**
* Returns an iterator that breaks its input into chunks and yields them one-by-one.
* @param data
* @param options
* @returns
* This function can e.g. be used to enable data sources that can only be read atomically
* (such as `Blob` and `File` via `FileReader`) to still be parsed in batches.
*/
function makeIterator(data, options) {
	if (typeof data === "string") return makeStringIterator(data, options);
	if (data instanceof ArrayBuffer) return makeArrayBufferIterator(data, options);
	if (isBlob(data)) return makeBlobIterator(data, options);
	if (isReadableStream(data)) return makeStreamIterator(data, options);
	if (isResponse(data)) {
		const responseBody = data.body;
		if (!responseBody) throw new Error("Readable stream not available on Response");
		return makeStreamIterator(responseBody, options);
	}
	throw new Error("makeIterator");
}
//#endregion
//#region node_modules/@loaders.gl/core/dist/lib/loader-utils/get-data.js
var ERR_DATA = "Cannot convert supplied data type";
/**
* Returns an {@link ArrayBuffer} or string from the provided data synchronously.
* Supports `ArrayBuffer`, `ArrayBufferView`, and `ArrayBufferLike` (e.g. `SharedArrayBuffer`)
* while preserving typed array view offsets.
*/
function getArrayBufferOrStringFromDataSync(data, loader, options) {
	if (loader.text && typeof data === "string") return data;
	if (isBuffer(data)) data = data.buffer;
	if (isArrayBufferLike(data)) {
		const bufferSource = toArrayBufferView(data);
		if (loader.text && !loader.binary) return new TextDecoder("utf8").decode(bufferSource);
		return toArrayBuffer(bufferSource);
	}
	throw new Error(ERR_DATA);
}
/**
* Resolves the provided data into an {@link ArrayBuffer} or string asynchronously.
* Accepts the full {@link DataType} surface including responses and async iterables.
*/
async function getArrayBufferOrStringFromData(data, loader, options) {
	if (typeof data === "string" || isArrayBufferLike(data)) return getArrayBufferOrStringFromDataSync(data, loader, options);
	if (isBlob(data)) data = await makeResponse(data);
	if (isResponse(data)) {
		await checkResponse(data);
		return loader.binary ? await data.arrayBuffer() : await data.text();
	}
	if (isReadableStream(data)) data = makeIterator(data, options);
	if (isIterable(data) || isAsyncIterable(data)) return concatenateArrayBuffersAsync(data);
	throw new Error(ERR_DATA);
}
//#endregion
//#region node_modules/@loaders.gl/core/dist/lib/loader-utils/get-fetch-function.js
/**
* Gets the current fetch function from options and context
* @param options
* @param context
*/
function getFetchFunction(options, context) {
	const globalOptions = getGlobalLoaderOptions();
	const loaderOptions = options || globalOptions;
	const fetchOption = loaderOptions.fetch ?? loaderOptions.core?.fetch;
	if (typeof fetchOption === "function") return fetchOption;
	if (isObject(fetchOption)) return (url) => fetchFile(url, fetchOption);
	if (context?.fetch) return context?.fetch;
	return fetchFile;
}
//#endregion
//#region node_modules/@loaders.gl/core/dist/lib/loader-utils/loader-context.js
/**
* "sub" loaders invoked by other loaders get a "context" injected on `this`
* The context will inject core methods like `parse` and contain information
* about loaders and options passed in to the top-level `parse` call.
*
* @param context
* @param options
* @param previousContext
*/
function getLoaderContext(context, options, parentContext) {
	if (parentContext) return parentContext;
	const newContext = {
		fetch: getFetchFunction(options, context),
		...context
	};
	if (newContext.url) {
		const baseUrl = stripQueryString(newContext.url);
		newContext.baseUrl = baseUrl;
		newContext.queryString = extractQueryString(newContext.url);
		newContext.filename = filename(baseUrl);
		newContext.baseUrl = dirname(baseUrl);
	}
	if (!Array.isArray(newContext.loaders)) newContext.loaders = null;
	return newContext;
}
function getLoadersFromContext(loaders, context) {
	if (loaders && !Array.isArray(loaders)) return loaders;
	let candidateLoaders;
	if (loaders) candidateLoaders = Array.isArray(loaders) ? loaders : [loaders];
	if (context && context.loaders) {
		const contextLoaders = Array.isArray(context.loaders) ? context.loaders : [context.loaders];
		candidateLoaders = candidateLoaders ? [...candidateLoaders, ...contextLoaders] : contextLoaders;
	}
	return candidateLoaders && candidateLoaders.length ? candidateLoaders : void 0;
}
//#endregion
//#region node_modules/@loaders.gl/core/dist/lib/api/parse.js
/**
* Parses `data` using a specified loader
* @param data
* @param loaders
* @param options
* @param context
*/
async function parse(data, loaders, options, context) {
	if (loaders && !Array.isArray(loaders) && !isLoaderObject(loaders)) {
		context = void 0;
		options = loaders;
		loaders = void 0;
	}
	data = await data;
	options = options || {};
	const url = getResourceUrl(data);
	const candidateLoaders = getLoadersFromContext(loaders, context);
	const loader = await selectLoader(data, candidateLoaders, options);
	if (!loader) return null;
	const strictOptions = normalizeOptions(options, loader, candidateLoaders, url);
	context = getLoaderContext({
		url,
		_parse: parse,
		loaders: candidateLoaders
	}, strictOptions, context || null);
	return await parseWithLoader(loader, data, strictOptions, context);
}
async function parseWithLoader(loader, data, options, context) {
	validateWorkerVersion(loader);
	options = mergeOptions(loader.options, options);
	if (isResponse(data)) {
		const { ok, redirected, status, statusText, type, url } = data;
		context.response = {
			headers: Object.fromEntries(data.headers.entries()),
			ok,
			redirected,
			status,
			statusText,
			type,
			url
		};
	}
	data = await getArrayBufferOrStringFromData(data, loader, options);
	const loaderWithParser = loader;
	if (loaderWithParser.parseTextSync && typeof data === "string") return loaderWithParser.parseTextSync(data, options, context);
	if (canParseWithWorker(loader, options)) return await parseWithWorker(loader, data, options, context, parse);
	if (loaderWithParser.parseText && typeof data === "string") return await loaderWithParser.parseText(data, options, context);
	if (loaderWithParser.parse) return await loaderWithParser.parse(data, options, context);
	assert$4(!loaderWithParser.parseSync);
	throw new Error(`${loader.id} loader - no parser found and worker is disabled`);
}
//#endregion
//#region node_modules/@loaders.gl/core/dist/lib/api/load.js
async function load(url, loaders, options, context) {
	let resolvedLoaders;
	let resolvedOptions;
	if (!Array.isArray(loaders) && !isLoaderObject(loaders)) {
		resolvedLoaders = [];
		resolvedOptions = loaders;
		context = void 0;
	} else {
		resolvedLoaders = loaders;
		resolvedOptions = options;
	}
	const fetch = getFetchFunction(resolvedOptions);
	let data = url;
	if (typeof url === "string") data = await fetch(url);
	if (isBlob(url)) data = await fetch(url);
	if (typeof url === "string") {
		if (!normalizeLoaderOptions(resolvedOptions || {}).core?.baseUrl) resolvedOptions = {
			...resolvedOptions,
			core: {
				...resolvedOptions?.core,
				baseUrl: url
			}
		};
	}
	return Array.isArray(resolvedLoaders) ? await parse(data, resolvedLoaders, resolvedOptions) : await parse(data, resolvedLoaders, resolvedOptions);
}
//#endregion
//#region node_modules/@deck.gl/core/dist/utils/log.js
var defaultLogger = new ProbeLog({ id: "deck" });
//#endregion
//#region node_modules/@deck.gl/core/dist/debug/loggers.js
var logState = {
	attributeUpdateStart: -1,
	attributeManagerUpdateStart: -1,
	attributeUpdateMessages: []
};
var LOG_LEVEL_MAJOR_UPDATE = 1;
var LOG_LEVEL_MINOR_UPDATE = 2;
var LOG_LEVEL_UPDATE_DETAIL = 3;
var LOG_LEVEL_INFO = 4;
var LOG_LEVEL_DRAW = 2;
var getLoggers = (log) => ({
	"layer.changeFlag": (layer, key, flags) => {
		log.log(LOG_LEVEL_UPDATE_DETAIL, `${layer.id} ${key}: `, flags[key])();
	},
	"layer.initialize": (layer) => {
		log.log(LOG_LEVEL_MAJOR_UPDATE, `Initializing ${layer}`)();
	},
	"layer.update": (layer, needsUpdate) => {
		if (needsUpdate) {
			const flags = layer.getChangeFlags();
			log.log(LOG_LEVEL_MINOR_UPDATE, `Updating ${layer} because: ${Object.keys(flags).filter((key) => flags[key]).join(", ")}`)();
		} else log.log(LOG_LEVEL_INFO, `${layer} does not need update`)();
	},
	"layer.matched": (layer, changed) => {
		if (changed) log.log(LOG_LEVEL_INFO, `Matched ${layer}, state transfered`)();
	},
	"layer.finalize": (layer) => {
		log.log(LOG_LEVEL_MAJOR_UPDATE, `Finalizing ${layer}`)();
	},
	"compositeLayer.renderLayers": (layer, updated, subLayers) => {
		if (updated) log.log(LOG_LEVEL_MINOR_UPDATE, `Composite layer rendered new subLayers ${layer}`, subLayers)();
		else log.log(LOG_LEVEL_INFO, `Composite layer reused subLayers ${layer}`, subLayers)();
	},
	"layerManager.setLayers": (layerManager, updated, layers) => {
		if (updated) log.log(LOG_LEVEL_MINOR_UPDATE, `Updating ${layers.length} deck layers`)();
	},
	"layerManager.activateViewport": (layerManager, viewport) => {
		log.log(LOG_LEVEL_UPDATE_DETAIL, "Viewport changed", viewport)();
	},
	"attributeManager.invalidate": (attributeManager, trigger, attributeNames) => {
		log.log(LOG_LEVEL_MAJOR_UPDATE, attributeNames ? `invalidated attributes ${attributeNames} (${trigger}) for ${attributeManager.id}` : `invalidated all attributes for ${attributeManager.id}`)();
	},
	"attributeManager.updateStart": (attributeManager) => {
		logState.attributeUpdateMessages.length = 0;
		logState.attributeManagerUpdateStart = Date.now();
	},
	"attributeManager.updateEnd": (attributeManager, numInstances) => {
		const timeMs = Math.round(Date.now() - logState.attributeManagerUpdateStart);
		log.groupCollapsed(LOG_LEVEL_MINOR_UPDATE, `Updated attributes for ${numInstances} instances in ${attributeManager.id} in ${timeMs}ms`)();
		for (const updateMessage of logState.attributeUpdateMessages) log.log(LOG_LEVEL_UPDATE_DETAIL, updateMessage)();
		log.groupEnd(LOG_LEVEL_MINOR_UPDATE)();
	},
	"attribute.updateStart": (attribute) => {
		logState.attributeUpdateStart = Date.now();
	},
	"attribute.allocate": (attribute, numInstances) => {
		const message = `${attribute.id} allocated ${numInstances}`;
		logState.attributeUpdateMessages.push(message);
	},
	"attribute.updateEnd": (attribute, numInstances) => {
		const timeMs = Math.round(Date.now() - logState.attributeUpdateStart);
		const message = `${attribute.id} updated ${numInstances} in ${timeMs}ms`;
		logState.attributeUpdateMessages.push(message);
	},
	"deckRenderer.renderLayers": (deckRenderer, renderStats, opts) => {
		const { pass, redrawReason } = opts;
		for (const status of renderStats) {
			const { totalCount, visibleCount, compositeCount, pickableCount } = status;
			const hiddenCount = totalCount - compositeCount - visibleCount;
			log.log(LOG_LEVEL_DRAW, `RENDER #${deckRenderer.renderCount} \
  ${visibleCount} (of ${totalCount} layers) to ${pass} because ${redrawReason} \
  (${hiddenCount} hidden, ${compositeCount} composite ${pickableCount} pickable)`)();
		}
	}
});
//#endregion
//#region node_modules/@deck.gl/core/dist/debug/index.js
var loggers = {};
loggers = getLoggers(defaultLogger);
function register(handlers) {
	loggers = handlers;
}
function debug(eventType, arg1, arg2, arg3) {
	if (defaultLogger.level > 0 && loggers[eventType]) loggers[eventType].call(null, arg1, arg2, arg3);
}
//#endregion
//#region node_modules/@luma.gl/shadertools/dist/lib/utils/assert.js
function assert$3(condition, message) {
	if (!condition) {
		const error = new Error(message || "shadertools: assertion failed.");
		Error.captureStackTrace?.(error, assert$3);
		throw error;
	}
}
//#endregion
//#region node_modules/@luma.gl/shadertools/dist/lib/filters/prop-types.js
/** Minimal validators for number and array types */
var DEFAULT_PROP_VALIDATORS = {
	number: {
		type: "number",
		validate(value, propType) {
			return Number.isFinite(value) && typeof propType === "object" && (propType.max === void 0 || value <= propType.max) && (propType.min === void 0 || value >= propType.min);
		}
	},
	array: {
		type: "array",
		validate(value, propType) {
			return Array.isArray(value) || ArrayBuffer.isView(value);
		}
	}
};
/**
* Parse a list of property types into property definitions that can be used to validate
* values passed in by applications.
* @param propTypes
* @returns
*/
function makePropValidators(propTypes) {
	const propValidators = {};
	for (const [name, propType] of Object.entries(propTypes)) propValidators[name] = makePropValidator(propType);
	return propValidators;
}
/**
* Creates a property validator for a prop type. Either contains:
* - a valid prop type object ({type, ...})
* - or just a default value, in which case type and name inference is used
*/
function makePropValidator(propType) {
	let type = getTypeOf(propType);
	if (type !== "object") return {
		value: propType,
		...DEFAULT_PROP_VALIDATORS[type],
		type
	};
	if (typeof propType === "object") {
		if (!propType) return {
			type: "object",
			value: null
		};
		if (propType.type !== void 0) return {
			...propType,
			...DEFAULT_PROP_VALIDATORS[propType.type],
			type: propType.type
		};
		if (propType.value === void 0) return {
			type: "object",
			value: propType
		};
		type = getTypeOf(propType.value);
		return {
			...propType,
			...DEFAULT_PROP_VALIDATORS[type],
			type
		};
	}
	throw new Error("props");
}
/**
* "improved" version of javascript typeof that can distinguish arrays and null values
*/
function getTypeOf(value) {
	if (Array.isArray(value) || ArrayBuffer.isView(value)) return "array";
	return typeof value;
}
//#endregion
//#region node_modules/@luma.gl/shadertools/dist/lib/shader-assembly/shader-injections.js
var MODULE_INJECTORS = {
	vertex: `\
#ifdef MODULE_LOGDEPTH
  logdepth_adjustPosition(gl_Position);
#endif
`,
	fragment: `\
#ifdef MODULE_MATERIAL
  fragColor = material_filterColor(fragColor);
#endif

#ifdef MODULE_LIGHTING
  fragColor = lighting_filterColor(fragColor);
#endif

#ifdef MODULE_FOG
  fragColor = fog_filterColor(fragColor);
#endif

#ifdef MODULE_PICKING
  fragColor = picking_filterHighlightColor(fragColor);
  fragColor = picking_filterPickingColor(fragColor);
#endif

#ifdef MODULE_LOGDEPTH
  logdepth_setFragDepth();
#endif
`
};
var REGEX_START_OF_MAIN = /void\s+main\s*\([^)]*\)\s*\{\n?/;
var REGEX_END_OF_MAIN = /}\n?[^{}]*$/;
var fragments = [];
var DECLARATION_INJECT_MARKER = "__LUMA_INJECT_DECLARATIONS__";
/**
*
*/
function normalizeInjections(injections) {
	const result = {
		vertex: {},
		fragment: {}
	};
	for (const hook in injections) {
		let injection = injections[hook];
		const stage = getHookStage(hook);
		if (typeof injection === "string") injection = {
			order: 0,
			injection
		};
		result[stage][hook] = injection;
	}
	return result;
}
function getHookStage(hook) {
	const type = hook.slice(0, 2);
	switch (type) {
		case "vs": return "vertex";
		case "fs": return "fragment";
		default: throw new Error(type);
	}
}
/**
// A minimal shader injection/templating system.
// RFC: https://github.com/visgl/luma.gl/blob/7.0-release/dev-docs/RFCs/v6.0/shader-injection-rfc.md
* @param source
* @param type
* @param inject
* @param injectStandardStubs
* @returns
*/
function injectShader(source, stage, inject, injectStandardStubs = false) {
	const isVertex = stage === "vertex";
	for (const key in inject) {
		const fragmentData = inject[key];
		fragmentData.sort((a, b) => a.order - b.order);
		fragments.length = fragmentData.length;
		for (let i = 0, len = fragmentData.length; i < len; ++i) fragments[i] = fragmentData[i].injection;
		const fragmentString = `${fragments.join("\n")}\n`;
		switch (key) {
			case "vs:#decl":
				if (isVertex) source = source.replace(DECLARATION_INJECT_MARKER, fragmentString);
				break;
			case "vs:#main-start":
				if (isVertex) source = source.replace(REGEX_START_OF_MAIN, (match) => match + fragmentString);
				break;
			case "vs:#main-end":
				if (isVertex) source = source.replace(REGEX_END_OF_MAIN, (match) => fragmentString + match);
				break;
			case "fs:#decl":
				if (!isVertex) source = source.replace(DECLARATION_INJECT_MARKER, fragmentString);
				break;
			case "fs:#main-start":
				if (!isVertex) source = source.replace(REGEX_START_OF_MAIN, (match) => match + fragmentString);
				break;
			case "fs:#main-end":
				if (!isVertex) source = source.replace(REGEX_END_OF_MAIN, (match) => fragmentString + match);
				break;
			default: source = source.replace(key, (match) => match + fragmentString);
		}
	}
	source = source.replace(DECLARATION_INJECT_MARKER, "");
	if (injectStandardStubs) source = source.replace(/\}\s*$/, (match) => match + MODULE_INJECTORS[stage]);
	return source;
}
//#endregion
//#region node_modules/@luma.gl/shadertools/dist/lib/shader-module/shader-module.js
function initializeShaderModules(modules) {
	modules.map((module) => initializeShaderModule(module));
}
function initializeShaderModule(module) {
	if (module.instance) return;
	initializeShaderModules(module.dependencies || []);
	const { propTypes = {}, deprecations = [], inject = {} } = module;
	const instance = {
		normalizedInjections: normalizeInjections(inject),
		parsedDeprecations: parseDeprecationDefinitions(deprecations)
	};
	if (propTypes) instance.propValidators = makePropValidators(propTypes);
	module.instance = instance;
	let defaultProps = {};
	if (propTypes) defaultProps = Object.entries(propTypes).reduce((obj, [key, propType]) => {
		const value = propType?.value;
		if (value) obj[key] = value;
		return obj;
	}, {});
	module.defaultUniforms = {
		...module.defaultUniforms,
		...defaultProps
	};
}
function checkShaderModuleDeprecations(shaderModule, shaderSource, log) {
	shaderModule.deprecations?.forEach((def) => {
		if (def.regex?.test(shaderSource)) if (def.deprecated) log.deprecated(def.old, def.new)();
		else log.removed(def.old, def.new)();
	});
}
function parseDeprecationDefinitions(deprecations) {
	deprecations.forEach((def) => {
		switch (def.type) {
			case "function":
				def.regex = new RegExp(`\\b${def.old}\\(`);
				break;
			default: def.regex = new RegExp(`${def.type} ${def.old};`);
		}
	});
	return deprecations;
}
//#endregion
//#region node_modules/@luma.gl/shadertools/dist/lib/shader-module/shader-module-dependencies.js
/**
* Takes a list of shader module names and returns a new list of
* shader module names that includes all dependencies, sorted so
* that modules that are dependencies of other modules come first.
*
* If the shader glsl code from the returned modules is concatenated
* in the reverse order, it is guaranteed that all functions be resolved and
* that all function and variable definitions come before use.
*
* @param modules - Array of modules (inline modules or module names)
* @return - Array of modules
*/
function getShaderModuleDependencies(modules) {
	initializeShaderModules(modules);
	const moduleMap = {};
	const moduleDepth = {};
	getDependencyGraph({
		modules,
		level: 0,
		moduleMap,
		moduleDepth
	});
	const dependencies = Object.keys(moduleDepth).sort((a, b) => moduleDepth[b] - moduleDepth[a]).map((name) => moduleMap[name]);
	initializeShaderModules(dependencies);
	return dependencies;
}
/**
* Recursively checks module dependencies to calculate dependency level of each module.
*
* @param options.modules - Array of modules
* @param options.level - Current level
* @param options.moduleMap -
* @param options.moduleDepth - Current level
* @return - Map of module name to its level
*/
function getDependencyGraph(options) {
	const { modules, level, moduleMap, moduleDepth } = options;
	if (level >= 5) throw new Error("Possible loop in shader dependency graph");
	for (const module of modules) {
		moduleMap[module.name] = module;
		if (moduleDepth[module.name] === void 0 || moduleDepth[module.name] < level) moduleDepth[module.name] = level;
	}
	for (const module of modules) if (module.dependencies) getDependencyGraph({
		modules: module.dependencies,
		level: level + 1,
		moduleMap,
		moduleDepth
	});
}
//#endregion
//#region node_modules/@luma.gl/shadertools/dist/lib/shader-module/shader-module-uniform-layout.js
/**
* Matches one field declaration inside a GLSL uniform block body.
*/
var GLSL_UNIFORM_BLOCK_FIELD_REGEXP = /^(?:uniform\s+)?(?:(?:lowp|mediump|highp)\s+)?[A-Za-z0-9_]+(?:<[^>]+>)?\s+([A-Za-z0-9_]+)(?:\s*\[[^\]]+\])?\s*;/;
/**
* Matches full GLSL uniform block declarations, including optional layout qualifiers.
*/
var GLSL_UNIFORM_BLOCK_REGEXP = /((?:layout\s*\([^)]*\)\s*)*)uniform\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{([\s\S]*?)\}\s*([A-Za-z_][A-Za-z0-9_]*)?\s*;/g;
/**
* Returns the uniform block type name expected for the supplied shader module.
*/
function getShaderModuleUniformBlockName(module) {
	return `${module.name}Uniforms`;
}
/**
* Returns the ordered field names parsed from a shader module's uniform block.
*
* @returns `null` when the stage has no source or the expected block is absent.
*/
function getShaderModuleUniformBlockFields(module, stage) {
	const shaderSource = stage === "wgsl" ? module.source : stage === "vertex" ? module.vs : module.fs;
	if (!shaderSource) return null;
	const uniformBlockName = getShaderModuleUniformBlockName(module);
	return extractShaderUniformBlockFieldNames(shaderSource, stage === "wgsl" ? "wgsl" : "glsl", uniformBlockName);
}
/**
* Computes the validation result for a shader module's declared and parsed
* uniform-block field lists.
*
* @returns `null` when the module has no declared uniform types or no matching block.
*/
function getShaderModuleUniformLayoutValidationResult(module, stage) {
	const expectedUniformNames = Object.keys(module.uniformTypes || {});
	if (!expectedUniformNames.length) return null;
	const actualUniformNames = getShaderModuleUniformBlockFields(module, stage);
	if (!actualUniformNames) return null;
	return {
		moduleName: module.name,
		uniformBlockName: getShaderModuleUniformBlockName(module),
		stage,
		expectedUniformNames,
		actualUniformNames,
		matches: areStringArraysEqual(expectedUniformNames, actualUniformNames)
	};
}
/**
* Validates that a shader module's parsed uniform block matches `uniformTypes`.
*
* When a mismatch is detected, the helper logs a formatted error and optionally
* throws via {@link assert}.
*/
function validateShaderModuleUniformLayout(module, stage, options = {}) {
	const validationResult = getShaderModuleUniformLayoutValidationResult(module, stage);
	if (!validationResult || validationResult.matches) return validationResult;
	const message = formatShaderModuleUniformLayoutError(validationResult);
	options.log?.error?.(message, validationResult)();
	if (options.throwOnError !== false) assert$3(false, message);
	return validationResult;
}
/**
* Parses all GLSL uniform blocks in a shader source string.
*/
function getGLSLUniformBlocks(shaderSource) {
	const blocks = [];
	const uncommentedSource = stripShaderComments(shaderSource);
	for (const sourceMatch of uncommentedSource.matchAll(GLSL_UNIFORM_BLOCK_REGEXP)) {
		const layoutQualifier = sourceMatch[1]?.trim() || null;
		blocks.push({
			blockName: sourceMatch[2],
			body: sourceMatch[3],
			instanceName: sourceMatch[4] || null,
			layoutQualifier,
			hasLayoutQualifier: Boolean(layoutQualifier),
			isStd140: Boolean(layoutQualifier && /\blayout\s*\([^)]*\bstd140\b[^)]*\)/.exec(layoutQualifier))
		});
	}
	return blocks;
}
/**
* Emits warnings for GLSL uniform blocks that do not explicitly declare
* `layout(std140)`.
*
* @returns The list of parsed blocks that were considered non-compliant.
*/
function warnIfGLSLUniformBlocksAreNotStd140(shaderSource, stage, log, context) {
	const nonStd140Blocks = getGLSLUniformBlocks(shaderSource).filter((block) => !block.isStd140);
	const seenBlockNames = /* @__PURE__ */ new Set();
	for (const block of nonStd140Blocks) {
		if (seenBlockNames.has(block.blockName)) continue;
		seenBlockNames.add(block.blockName);
		const shaderLabel = context?.label ? `${context.label} ` : "";
		const actualLayout = block.hasLayoutQualifier ? `declares ${normalizeWhitespace(block.layoutQualifier)} instead of layout(std140)` : "does not declare layout(std140)";
		const message = `${shaderLabel}${stage} shader uniform block ${block.blockName} ${actualLayout}. luma.gl host-side shader block packing assumes explicit layout(std140) for GLSL uniform blocks. Add \`layout(std140)\` to the block declaration.`;
		log?.warn?.(message, block)();
	}
	return nonStd140Blocks;
}
/**
* Extracts field names from the named GLSL or WGSL uniform block/struct.
*/
function extractShaderUniformBlockFieldNames(shaderSource, language, uniformBlockName) {
	const sourceBody = language === "wgsl" ? extractWGSLStructBody(shaderSource, uniformBlockName) : extractGLSLUniformBlockBody(shaderSource, uniformBlockName);
	if (!sourceBody) return null;
	const fieldNames = [];
	for (const sourceLine of sourceBody.split("\n")) {
		const line = sourceLine.replace(/\/\/.*$/, "").trim();
		if (!line || line.startsWith("#")) continue;
		const fieldMatch = language === "wgsl" ? line.match(/^([A-Za-z0-9_]+)\s*:/) : line.match(GLSL_UNIFORM_BLOCK_FIELD_REGEXP);
		if (fieldMatch) fieldNames.push(fieldMatch[1]);
	}
	return fieldNames;
}
/**
* Extracts the body of a WGSL struct with the supplied name.
*/
function extractWGSLStructBody(shaderSource, uniformBlockName) {
	const structMatch = new RegExp(`\\bstruct\\s+${uniformBlockName}\\b`, "m").exec(shaderSource);
	if (!structMatch) return null;
	const openBraceIndex = shaderSource.indexOf("{", structMatch.index);
	if (openBraceIndex < 0) return null;
	let braceDepth = 0;
	for (let index = openBraceIndex; index < shaderSource.length; index++) {
		const character = shaderSource[index];
		if (character === "{") {
			braceDepth++;
			continue;
		}
		if (character !== "}") continue;
		braceDepth--;
		if (braceDepth === 0) return shaderSource.slice(openBraceIndex + 1, index);
	}
	return null;
}
/**
* Extracts the body of a named GLSL uniform block from shader source.
*/
function extractGLSLUniformBlockBody(shaderSource, uniformBlockName) {
	return getGLSLUniformBlocks(shaderSource).find((candidate) => candidate.blockName === uniformBlockName)?.body || null;
}
/**
* Returns `true` when the two arrays contain the same strings in the same order.
*/
function areStringArraysEqual(leftValues, rightValues) {
	if (leftValues.length !== rightValues.length) return false;
	for (let valueIndex = 0; valueIndex < leftValues.length; valueIndex++) if (leftValues[valueIndex] !== rightValues[valueIndex]) return false;
	return true;
}
/**
* Formats the standard validation error message for a shader-module layout mismatch.
*/
function formatShaderModuleUniformLayoutError(validationResult) {
	const { expectedUniformNames, actualUniformNames } = validationResult;
	const missingUniformNames = expectedUniformNames.filter((uniformName) => !actualUniformNames.includes(uniformName));
	const unexpectedUniformNames = actualUniformNames.filter((uniformName) => !expectedUniformNames.includes(uniformName));
	const mismatchDetails = [`Expected ${expectedUniformNames.length} fields, found ${actualUniformNames.length}.`];
	const firstMismatchDescription = getFirstUniformMismatchDescription(expectedUniformNames, actualUniformNames);
	if (firstMismatchDescription) mismatchDetails.push(firstMismatchDescription);
	if (missingUniformNames.length) mismatchDetails.push(`Missing from shader block (${missingUniformNames.length}): ${formatUniformNameList(missingUniformNames)}.`);
	if (unexpectedUniformNames.length) mismatchDetails.push(`Unexpected in shader block (${unexpectedUniformNames.length}): ${formatUniformNameList(unexpectedUniformNames)}.`);
	if (expectedUniformNames.length <= 12 && actualUniformNames.length <= 12 && (missingUniformNames.length || unexpectedUniformNames.length)) {
		mismatchDetails.push(`Expected: ${expectedUniformNames.join(", ")}.`);
		mismatchDetails.push(`Actual: ${actualUniformNames.join(", ")}.`);
	}
	return `${validationResult.moduleName}: ${validationResult.stage} shader uniform block ${validationResult.uniformBlockName} does not match module.uniformTypes. ${mismatchDetails.join(" ")}`;
}
/**
* Removes line and block comments from shader source before lightweight parsing.
*/
function stripShaderComments(shaderSource) {
	return shaderSource.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
}
/**
* Collapses repeated whitespace in a layout qualifier for log-friendly output.
*/
function normalizeWhitespace(value) {
	return value.replace(/\s+/g, " ").trim();
}
function getFirstUniformMismatchDescription(expectedUniformNames, actualUniformNames) {
	const minimumLength = Math.min(expectedUniformNames.length, actualUniformNames.length);
	for (let index = 0; index < minimumLength; index++) if (expectedUniformNames[index] !== actualUniformNames[index]) return `First mismatch at field ${index + 1}: expected ${expectedUniformNames[index]}, found ${actualUniformNames[index]}.`;
	if (expectedUniformNames.length > actualUniformNames.length) return `Shader block ends after field ${actualUniformNames.length}; expected next field ${expectedUniformNames[actualUniformNames.length]}.`;
	if (actualUniformNames.length > expectedUniformNames.length) return `Shader block has extra field ${actualUniformNames.length}: ${actualUniformNames[expectedUniformNames.length]}.`;
	return null;
}
function formatUniformNameList(uniformNames, maxNames = 8) {
	if (uniformNames.length <= maxNames) return uniformNames.join(", ");
	const remainingCount = uniformNames.length - maxNames;
	return `${uniformNames.slice(0, maxNames).join(", ")}, ... (${remainingCount} more)`;
}
//#endregion
//#region node_modules/@luma.gl/shadertools/dist/lib/shader-assembly/platform-defines.js
/** Adds defines to help identify GPU architecture / platform */
function getPlatformShaderDefines(platformInfo) {
	switch (platformInfo?.gpu.toLowerCase()) {
		case "apple": return `\
#define APPLE_GPU
// Apple optimizes away the calculation necessary for emulated fp64
#define LUMA_FP64_CODE_ELIMINATION_WORKAROUND 1
#define LUMA_FP32_TAN_PRECISION_WORKAROUND 1
// Intel GPU doesn't have full 32 bits precision in same cases, causes overflow
#define LUMA_FP64_HIGH_BITS_OVERFLOW_WORKAROUND 1
`;
		case "nvidia": return `\
#define NVIDIA_GPU
// Nvidia optimizes away the calculation necessary for emulated fp64
#define LUMA_FP64_CODE_ELIMINATION_WORKAROUND 1
`;
		case "intel": return `\
#define INTEL_GPU
// Intel optimizes away the calculation necessary for emulated fp64
#define LUMA_FP64_CODE_ELIMINATION_WORKAROUND 1
// Intel's built-in 'tan' function doesn't have acceptable precision
#define LUMA_FP32_TAN_PRECISION_WORKAROUND 1
// Intel GPU doesn't have full 32 bits precision in same cases, causes overflow
#define LUMA_FP64_HIGH_BITS_OVERFLOW_WORKAROUND 1
`;
		case "amd": return `\
#define AMD_GPU
`;
		default: return `\
#define DEFAULT_GPU
// Prevent driver from optimizing away the calculation necessary for emulated fp64
#define LUMA_FP64_CODE_ELIMINATION_WORKAROUND 1
// Headless Chrome's software shader 'tan' function doesn't have acceptable precision
#define LUMA_FP32_TAN_PRECISION_WORKAROUND 1
// If the GPU doesn't have full 32 bits precision, will causes overflow
#define LUMA_FP64_HIGH_BITS_OVERFLOW_WORKAROUND 1
`;
	}
}
//#endregion
//#region node_modules/@luma.gl/shadertools/dist/lib/shader-transpiler/transpile-glsl-shader.js
/**
* Transpiles GLSL 3.00 shader source code to target GLSL version (3.00 or 1.00)
*
* @note We always run transpiler even if same version e.g. 3.00 => 3.00
* @note For texture sampling transpilation, apps need to use non-standard texture* calls in GLSL 3.00 source
* RFC: https://github.com/visgl/luma.gl/blob/7.0-release/dev-docs/RFCs/v6.0/portable-glsl-300-rfc.md
*/
function transpileGLSLShader(source, stage) {
	if (Number(source.match(/^#version[ \t]+(\d+)/m)?.[1] || 100) !== 300) throw new Error("luma.gl v9 only supports GLSL 3.00 shader sources");
	switch (stage) {
		case "vertex":
			source = convertShader(source, ES300_VERTEX_REPLACEMENTS);
			return source;
		case "fragment":
			source = convertShader(source, ES300_FRAGMENT_REPLACEMENTS);
			return source;
		default: throw new Error(stage);
	}
}
/** Simple regex replacements for GLSL ES 1.00 syntax that has changed in GLSL ES 3.00 */
var ES300_REPLACEMENTS = [
	[/^(#version[ \t]+(100|300[ \t]+es))?[ \t]*\n/, "#version 300 es\n"],
	[/\btexture(2D|2DProj|Cube)Lod(EXT)?\(/g, "textureLod("],
	[/\btexture(2D|2DProj|Cube)(EXT)?\(/g, "texture("]
];
var ES300_VERTEX_REPLACEMENTS = [
	...ES300_REPLACEMENTS,
	[makeVariableTextRegExp("attribute"), "in $1"],
	[makeVariableTextRegExp("varying"), "out $1"]
];
/** Simple regex replacements for GLSL ES 1.00 syntax that has changed in GLSL ES 3.00 */
var ES300_FRAGMENT_REPLACEMENTS = [...ES300_REPLACEMENTS, [makeVariableTextRegExp("varying"), "in $1"]];
function convertShader(source, replacements) {
	for (const [pattern, replacement] of replacements) source = source.replace(pattern, replacement);
	return source;
}
/**
* Creates a regexp that tests for a specific variable type
* @example
*   should match:
*     in float weight;
*     out vec4 positions[2];
*   should not match:
*     void f(out float a, in float b) {}
*/
function makeVariableTextRegExp(qualifier) {
	return new RegExp(`\\b${qualifier}[ \\t]+(\\w+[ \\t]+\\w+(\\[\\w+\\])?;)`, "g");
}
//#endregion
//#region node_modules/@luma.gl/shadertools/dist/lib/shader-assembly/shader-hooks.js
/** Generate hook source code */
function getShaderHooks(hookFunctions, hookInjections) {
	let result = "";
	for (const hookName in hookFunctions) {
		const hookFunction = hookFunctions[hookName];
		result += `void ${hookFunction.signature} {\n`;
		if (hookFunction.header) result += `  ${hookFunction.header}`;
		if (hookInjections[hookName]) {
			const injections = hookInjections[hookName];
			injections.sort((a, b) => a.order - b.order);
			for (const injection of injections) result += `  ${injection.injection}\n`;
		}
		if (hookFunction.footer) result += `  ${hookFunction.footer}`;
		result += "}\n";
	}
	return result;
}
/**
* Parse string based hook functions
* And split per shader
*/
function normalizeShaderHooks(hookFunctions) {
	const result = {
		vertex: {},
		fragment: {}
	};
	for (const hookFunction of hookFunctions) {
		let opts;
		let hook;
		if (typeof hookFunction !== "string") {
			opts = hookFunction;
			hook = opts.hook;
		} else {
			opts = {};
			hook = hookFunction;
		}
		hook = hook.trim();
		const [shaderStage, signature] = hook.split(":");
		const name = hook.replace(/\(.+/, "");
		const normalizedHook = Object.assign(opts, { signature });
		switch (shaderStage) {
			case "vs":
				result.vertex[name] = normalizedHook;
				break;
			case "fs":
				result.fragment[name] = normalizedHook;
				break;
			default: throw new Error(shaderStage);
		}
	}
	return result;
}
//#endregion
//#region node_modules/@luma.gl/shadertools/dist/lib/glsl-utils/get-shader-info.js
/** Extracts information from shader source code */
function getShaderInfo(source, defaultName) {
	return {
		name: getShaderName(source, defaultName),
		language: "glsl",
		version: getShaderVersion(source)
	};
}
/** Extracts GLSLIFY style naming of shaders: `#define SHADER_NAME ...` */
function getShaderName(shader, defaultName = "unnamed") {
	const match = /#define[^\S\r\n]*SHADER_NAME[^\S\r\n]*([A-Za-z0-9_-]+)\s*/.exec(shader);
	return match ? match[1] : defaultName;
}
/** returns GLSL shader version of given shader string */
function getShaderVersion(source) {
	let version = 100;
	const words = source.match(/[^\s]+/g);
	if (words && words.length >= 2 && words[0] === "#version") {
		const parsedVersion = parseInt(words[1], 10);
		if (Number.isFinite(parsedVersion)) version = parsedVersion;
	}
	if (version !== 100 && version !== 300) throw new Error(`Invalid GLSL version ${version}`);
	return version;
}
//#endregion
//#region node_modules/@luma.gl/shadertools/dist/lib/shader-assembly/wgsl-binding-scan.js
var WGSL_BINDABLE_VARIABLE_PATTERN = "(?:var<\\s*(uniform|storage(?:\\s*,\\s*[A-Za-z_][A-Za-z0-9_]*)?)\\s*>|var)\\s+([A-Za-z_][A-Za-z0-9_]*)";
var WGSL_BINDING_DECLARATION_SEPARATOR_PATTERN = "\\s*";
var MODULE_WGSL_BINDING_DECLARATION_REGEXES = [new RegExp(`@binding\\(\\s*(auto|\\d+)\\s*\\)${WGSL_BINDING_DECLARATION_SEPARATOR_PATTERN}@group\\(\\s*(\\d+)\\s*\\)${WGSL_BINDING_DECLARATION_SEPARATOR_PATTERN}${WGSL_BINDABLE_VARIABLE_PATTERN}`, "g"), new RegExp(`@group\\(\\s*(\\d+)\\s*\\)${WGSL_BINDING_DECLARATION_SEPARATOR_PATTERN}@binding\\(\\s*(auto|\\d+)\\s*\\)${WGSL_BINDING_DECLARATION_SEPARATOR_PATTERN}${WGSL_BINDABLE_VARIABLE_PATTERN}`, "g")];
var WGSL_BINDING_DECLARATION_REGEXES = [new RegExp(`@binding\\(\\s*(auto|\\d+)\\s*\\)${WGSL_BINDING_DECLARATION_SEPARATOR_PATTERN}@group\\(\\s*(\\d+)\\s*\\)${WGSL_BINDING_DECLARATION_SEPARATOR_PATTERN}${WGSL_BINDABLE_VARIABLE_PATTERN}`, "g"), new RegExp(`@group\\(\\s*(\\d+)\\s*\\)${WGSL_BINDING_DECLARATION_SEPARATOR_PATTERN}@binding\\(\\s*(auto|\\d+)\\s*\\)${WGSL_BINDING_DECLARATION_SEPARATOR_PATTERN}${WGSL_BINDABLE_VARIABLE_PATTERN}`, "g")];
var WGSL_EXPLICIT_BINDING_DECLARATION_REGEXES = [new RegExp(`@binding\\(\\s*(\\d+)\\s*\\)${WGSL_BINDING_DECLARATION_SEPARATOR_PATTERN}@group\\(\\s*(\\d+)\\s*\\)${WGSL_BINDING_DECLARATION_SEPARATOR_PATTERN}${WGSL_BINDABLE_VARIABLE_PATTERN}`, "g"), new RegExp(`@group\\(\\s*(\\d+)\\s*\\)${WGSL_BINDING_DECLARATION_SEPARATOR_PATTERN}@binding\\(\\s*(\\d+)\\s*\\)${WGSL_BINDING_DECLARATION_SEPARATOR_PATTERN}${WGSL_BINDABLE_VARIABLE_PATTERN}`, "g")];
var WGSL_AUTO_BINDING_DECLARATION_REGEXES = [
	new RegExp(`@binding\\(\\s*(auto)\\s*\\)\\s*@group\\(\\s*(\\d+)\\s*\\)\\s*${WGSL_BINDABLE_VARIABLE_PATTERN}`, "g"),
	new RegExp(`@group\\(\\s*(\\d+)\\s*\\)\\s*@binding\\(\\s*(auto)\\s*\\)\\s*${WGSL_BINDABLE_VARIABLE_PATTERN}`, "g"),
	new RegExp(`@binding\\(\\s*(auto)\\s*\\)\\s*@group\\(\\s*(\\d+)\\s*\\)(?:[\\s\\n\\r]*@[A-Za-z_][^\\n\\r]*)*[\\s\\n\\r]*${WGSL_BINDABLE_VARIABLE_PATTERN}`, "g"),
	new RegExp(`@group\\(\\s*(\\d+)\\s*\\)\\s*@binding\\(\\s*(auto)\\s*\\)(?:[\\s\\n\\r]*@[A-Za-z_][^\\n\\r]*)*[\\s\\n\\r]*${WGSL_BINDABLE_VARIABLE_PATTERN}`, "g")
];
function maskWGSLComments(source) {
	const maskedCharacters = source.split("");
	let index = 0;
	let blockCommentDepth = 0;
	let inLineComment = false;
	let inString = false;
	let isEscaped = false;
	while (index < source.length) {
		const character = source[index];
		const nextCharacter = source[index + 1];
		if (inString) {
			if (isEscaped) isEscaped = false;
			else if (character === "\\") isEscaped = true;
			else if (character === "\"") inString = false;
			index++;
			continue;
		}
		if (inLineComment) {
			if (character === "\n" || character === "\r") inLineComment = false;
			else maskedCharacters[index] = " ";
			index++;
			continue;
		}
		if (blockCommentDepth > 0) {
			if (character === "/" && nextCharacter === "*") {
				maskedCharacters[index] = " ";
				maskedCharacters[index + 1] = " ";
				blockCommentDepth++;
				index += 2;
				continue;
			}
			if (character === "*" && nextCharacter === "/") {
				maskedCharacters[index] = " ";
				maskedCharacters[index + 1] = " ";
				blockCommentDepth--;
				index += 2;
				continue;
			}
			if (character !== "\n" && character !== "\r") maskedCharacters[index] = " ";
			index++;
			continue;
		}
		if (character === "\"") {
			inString = true;
			index++;
			continue;
		}
		if (character === "/" && nextCharacter === "/") {
			maskedCharacters[index] = " ";
			maskedCharacters[index + 1] = " ";
			inLineComment = true;
			index += 2;
			continue;
		}
		if (character === "/" && nextCharacter === "*") {
			maskedCharacters[index] = " ";
			maskedCharacters[index + 1] = " ";
			blockCommentDepth = 1;
			index += 2;
			continue;
		}
		index++;
	}
	return maskedCharacters.join("");
}
function getWGSLBindingDeclarationMatches(source, regexes) {
	const maskedSource = maskWGSLComments(source);
	const matches = [];
	for (const regex of regexes) {
		regex.lastIndex = 0;
		let match;
		match = regex.exec(maskedSource);
		while (match) {
			const isBindingFirst = regex === regexes[0];
			const index = match.index;
			const length = match[0].length;
			matches.push({
				match: source.slice(index, index + length),
				index,
				length,
				bindingToken: match[isBindingFirst ? 1 : 2],
				groupToken: match[isBindingFirst ? 2 : 1],
				accessDeclaration: match[3]?.trim(),
				name: match[4]
			});
			match = regex.exec(maskedSource);
		}
	}
	return matches.sort((left, right) => left.index - right.index);
}
function replaceWGSLBindingDeclarationMatches(source, regexes, replacer) {
	const matches = getWGSLBindingDeclarationMatches(source, regexes);
	if (!matches.length) return source;
	let relocatedSource = "";
	let lastIndex = 0;
	for (const match of matches) {
		relocatedSource += source.slice(lastIndex, match.index);
		relocatedSource += replacer(match);
		lastIndex = match.index + match.length;
	}
	relocatedSource += source.slice(lastIndex);
	return relocatedSource;
}
function hasWGSLAutoBinding(source) {
	return /@binding\(\s*auto\s*\)/.test(maskWGSLComments(source));
}
function getFirstWGSLAutoBindingDeclarationMatch(source, regexes) {
	return getWGSLBindingDeclarationMatches(source, regexes === MODULE_WGSL_BINDING_DECLARATION_REGEXES || regexes === WGSL_BINDING_DECLARATION_REGEXES ? WGSL_AUTO_BINDING_DECLARATION_REGEXES : regexes).find((declarationMatch) => declarationMatch.bindingToken === "auto");
}
//#endregion
//#region node_modules/@luma.gl/shadertools/dist/lib/shader-assembly/wgsl-binding-debug.js
var WGSL_BINDING_DEBUG_REGEXES = [new RegExp(`@binding\\(\\s*(\\d+)\\s*\\)\\s*@group\\(\\s*(\\d+)\\s*\\)\\s*${WGSL_BINDABLE_VARIABLE_PATTERN}\\s*:\\s*([^;]+);`, "g"), new RegExp(`@group\\(\\s*(\\d+)\\s*\\)\\s*@binding\\(\\s*(\\d+)\\s*\\)\\s*${WGSL_BINDABLE_VARIABLE_PATTERN}\\s*:\\s*([^;]+);`, "g")];
/** Builds a stable, table-friendly binding summary from assembled WGSL source. */
function getShaderBindingDebugRowsFromWGSL(source, bindingAssignments = []) {
	const maskedSource = maskWGSLComments(source);
	const assignmentMap = /* @__PURE__ */ new Map();
	for (const bindingAssignment of bindingAssignments) assignmentMap.set(getBindingAssignmentKey(bindingAssignment.name, bindingAssignment.group, bindingAssignment.location), bindingAssignment.moduleName);
	const rows = [];
	for (const regex of WGSL_BINDING_DEBUG_REGEXES) {
		regex.lastIndex = 0;
		let match;
		match = regex.exec(maskedSource);
		while (match) {
			const isBindingFirst = regex === WGSL_BINDING_DEBUG_REGEXES[0];
			const binding = Number(match[isBindingFirst ? 1 : 2]);
			const group = Number(match[isBindingFirst ? 2 : 1]);
			const accessDeclaration = match[3]?.trim();
			const name = match[4];
			const resourceType = match[5].trim();
			const moduleName = assignmentMap.get(getBindingAssignmentKey(name, group, binding));
			rows.push(normalizeShaderBindingDebugRow({
				name,
				group,
				binding,
				owner: moduleName ? "module" : "application",
				moduleName,
				accessDeclaration,
				resourceType
			}));
			match = regex.exec(maskedSource);
		}
	}
	return rows.sort((left, right) => {
		if (left.group !== right.group) return left.group - right.group;
		if (left.binding !== right.binding) return left.binding - right.binding;
		return left.name.localeCompare(right.name);
	});
}
function normalizeShaderBindingDebugRow(row) {
	const baseRow = {
		name: row.name,
		group: row.group,
		binding: row.binding,
		owner: row.owner,
		kind: "unknown",
		moduleName: row.moduleName,
		resourceType: row.resourceType
	};
	if (row.accessDeclaration) {
		const access = row.accessDeclaration.split(",").map((value) => value.trim());
		if (access[0] === "uniform") return {
			...baseRow,
			kind: "uniform",
			access: "uniform"
		};
		if (access[0] === "storage") {
			const storageAccess = access[1] || "read_write";
			return {
				...baseRow,
				kind: storageAccess === "read" ? "read-only-storage" : "storage",
				access: storageAccess
			};
		}
	}
	if (row.resourceType === "sampler" || row.resourceType === "sampler_comparison") return {
		...baseRow,
		kind: "sampler",
		samplerKind: row.resourceType === "sampler_comparison" ? "comparison" : "filtering"
	};
	if (row.resourceType.startsWith("texture_storage_")) return {
		...baseRow,
		kind: "storage-texture",
		access: getStorageTextureAccess(row.resourceType),
		viewDimension: getTextureViewDimension(row.resourceType)
	};
	if (row.resourceType.startsWith("texture_")) return {
		...baseRow,
		kind: "texture",
		viewDimension: getTextureViewDimension(row.resourceType),
		sampleType: getTextureSampleType(row.resourceType),
		multisampled: row.resourceType.startsWith("texture_multisampled_")
	};
	return baseRow;
}
function getBindingAssignmentKey(name, group, binding) {
	return `${group}:${binding}:${name}`;
}
function getTextureViewDimension(resourceType) {
	if (resourceType.includes("cube_array")) return "cube-array";
	if (resourceType.includes("2d_array")) return "2d-array";
	if (resourceType.includes("cube")) return "cube";
	if (resourceType.includes("3d")) return "3d";
	if (resourceType.includes("2d")) return "2d";
	if (resourceType.includes("1d")) return "1d";
}
function getTextureSampleType(resourceType) {
	if (resourceType.startsWith("texture_depth_")) return "depth";
	if (resourceType.includes("<i32>")) return "sint";
	if (resourceType.includes("<u32>")) return "uint";
	if (resourceType.includes("<f32>")) return "float";
}
function getStorageTextureAccess(resourceType) {
	return /,\s*([A-Za-z_][A-Za-z0-9_]*)\s*>$/.exec(resourceType)?.[1];
}
//#endregion
//#region node_modules/@luma.gl/shadertools/dist/lib/shader-assembly/assemble-shaders.js
var INJECT_SHADER_DECLARATIONS = `\n\n${DECLARATION_INJECT_MARKER}\n`;
var RESERVED_APPLICATION_GROUP_0_BINDING_LIMIT = 100;
/**
* Precision prologue to inject before functions are injected in shader
* TODO - extract any existing prologue in the fragment source and move it up...
*/
var FRAGMENT_SHADER_PROLOGUE = `\
precision highp float;
`;
/**
* Inject a list of shader modules into a single shader source for WGSL
*/
function assembleWGSLShader(options) {
	const modules = getShaderModuleDependencies(options.modules || []);
	const { source, bindingAssignments } = assembleShaderWGSL(options.platformInfo, {
		...options,
		source: options.source,
		stage: "vertex",
		modules
	});
	return {
		source,
		getUniforms: assembleGetUniforms(modules),
		bindingAssignments,
		bindingTable: getShaderBindingDebugRowsFromWGSL(source, bindingAssignments)
	};
}
/**
* Injects dependent shader module sources into pair of main vertex/fragment shader sources for GLSL
*/
function assembleGLSLShaderPair(options) {
	const { vs, fs } = options;
	const modules = getShaderModuleDependencies(options.modules || []);
	return {
		vs: assembleShaderGLSL(options.platformInfo, {
			...options,
			source: vs,
			stage: "vertex",
			modules
		}),
		fs: assembleShaderGLSL(options.platformInfo, {
			...options,
			source: fs,
			stage: "fragment",
			modules
		}),
		getUniforms: assembleGetUniforms(modules)
	};
}
/**
* Pulls together complete source code for either a vertex or a fragment shader
* adding prologues, requested module chunks, and any final injections.
* @param gl
* @param options
* @returns
*/
function assembleShaderWGSL(platformInfo, options) {
	const { source, stage, modules, hookFunctions = [], inject = {}, log } = options;
	assert$3(typeof source === "string", "shader source must be a string");
	const coreSource = source;
	let assembledSource = "";
	const hookFunctionMap = normalizeShaderHooks(hookFunctions);
	const hookInjections = {};
	const declInjections = {};
	const mainInjections = {};
	for (const key in inject) {
		const injection = typeof inject[key] === "string" ? {
			injection: inject[key],
			order: 0
		} : inject[key];
		const match = /^(v|f)s:(#)?([\w-]+)$/.exec(key);
		if (match) {
			const hash = match[2];
			const name = match[3];
			if (hash) if (name === "decl") declInjections[key] = [injection];
			else mainInjections[key] = [injection];
			else hookInjections[key] = [injection];
		} else mainInjections[key] = [injection];
	}
	const modulesToInject = modules;
	const applicationRelocation = relocateWGSLApplicationBindings(coreSource);
	const usedBindingsByGroup = getUsedBindingsByGroupFromApplicationWGSL(applicationRelocation.source);
	const reservedBindingKeysByGroup = reserveRegisteredModuleBindings(modulesToInject, options._bindingRegistry, usedBindingsByGroup);
	const bindingAssignments = [];
	for (const module of modulesToInject) {
		if (log) checkShaderModuleDeprecations(module, coreSource, log);
		const relocation = relocateWGSLModuleBindings(getShaderModuleSource(module, "wgsl", log), module, {
			usedBindingsByGroup,
			bindingRegistry: options._bindingRegistry,
			reservedBindingKeysByGroup
		});
		bindingAssignments.push(...relocation.bindingAssignments);
		const moduleSource = relocation.source;
		assembledSource += moduleSource;
		const injections = module.injections?.[stage] || {};
		for (const key in injections) {
			const match = /^(v|f)s:#([\w-]+)$/.exec(key);
			if (match) {
				const injectionType = match[2] === "decl" ? declInjections : mainInjections;
				injectionType[key] = injectionType[key] || [];
				injectionType[key].push(injections[key]);
			} else {
				hookInjections[key] = hookInjections[key] || [];
				hookInjections[key].push(injections[key]);
			}
		}
	}
	assembledSource += INJECT_SHADER_DECLARATIONS;
	assembledSource = injectShader(assembledSource, stage, declInjections);
	assembledSource += getShaderHooks(hookFunctionMap[stage], hookInjections);
	assembledSource += formatWGSLBindingAssignmentComments(bindingAssignments);
	assembledSource += applicationRelocation.source;
	assembledSource = injectShader(assembledSource, stage, mainInjections);
	assertNoUnresolvedAutoBindings(assembledSource);
	return {
		source: assembledSource,
		bindingAssignments
	};
}
/**
* Pulls together complete source code for either a vertex or a fragment shader
* adding prologues, requested module chunks, and any final injections.
* @param gl
* @param options
* @returns
*/
function assembleShaderGLSL(platformInfo, options) {
	const { source, stage, language = "glsl", modules, defines = {}, hookFunctions = [], inject = {}, prologue = true, log } = options;
	assert$3(typeof source === "string", "shader source must be a string");
	const sourceVersion = language === "glsl" ? getShaderInfo(source).version : -1;
	const targetVersion = platformInfo.shaderLanguageVersion;
	const sourceVersionDirective = sourceVersion === 100 ? "#version 100" : "#version 300 es";
	const coreSource = source.split("\n").slice(1).join("\n");
	const allDefines = {};
	modules.forEach((module) => {
		Object.assign(allDefines, module.defines);
	});
	Object.assign(allDefines, defines);
	let assembledSource = "";
	switch (language) {
		case "wgsl": break;
		case "glsl":
			assembledSource = prologue ? `\
${sourceVersionDirective}

// ----- PROLOGUE -------------------------
${`#define SHADER_TYPE_${stage.toUpperCase()}`}

${getPlatformShaderDefines(platformInfo)}
${stage === "fragment" ? FRAGMENT_SHADER_PROLOGUE : ""}

// ----- APPLICATION DEFINES -------------------------

${getApplicationDefines(allDefines)}

` : `${sourceVersionDirective}
`;
			break;
	}
	const hookFunctionMap = normalizeShaderHooks(hookFunctions);
	const hookInjections = {};
	const declInjections = {};
	const mainInjections = {};
	for (const key in inject) {
		const injection = typeof inject[key] === "string" ? {
			injection: inject[key],
			order: 0
		} : inject[key];
		const match = /^(v|f)s:(#)?([\w-]+)$/.exec(key);
		if (match) {
			const hash = match[2];
			const name = match[3];
			if (hash) if (name === "decl") declInjections[key] = [injection];
			else mainInjections[key] = [injection];
			else hookInjections[key] = [injection];
		} else mainInjections[key] = [injection];
	}
	for (const module of modules) {
		if (log) checkShaderModuleDeprecations(module, coreSource, log);
		const moduleSource = getShaderModuleSource(module, stage, log);
		assembledSource += moduleSource;
		const injections = module.instance?.normalizedInjections[stage] || {};
		for (const key in injections) {
			const match = /^(v|f)s:#([\w-]+)$/.exec(key);
			if (match) {
				const injectionType = match[2] === "decl" ? declInjections : mainInjections;
				injectionType[key] = injectionType[key] || [];
				injectionType[key].push(injections[key]);
			} else {
				hookInjections[key] = hookInjections[key] || [];
				hookInjections[key].push(injections[key]);
			}
		}
	}
	assembledSource += "// ----- MAIN SHADER SOURCE -------------------------";
	assembledSource += INJECT_SHADER_DECLARATIONS;
	assembledSource = injectShader(assembledSource, stage, declInjections);
	assembledSource += getShaderHooks(hookFunctionMap[stage], hookInjections);
	assembledSource += coreSource;
	assembledSource = injectShader(assembledSource, stage, mainInjections);
	if (language === "glsl" && sourceVersion !== targetVersion) assembledSource = transpileGLSLShader(assembledSource, stage);
	if (language === "glsl") warnIfGLSLUniformBlocksAreNotStd140(assembledSource, stage, log);
	return assembledSource.trim();
}
/**
* Returns a combined `getUniforms` covering the options for all the modules,
* the created function will pass on options to the inidividual `getUniforms`
* function of each shader module and combine the results into one object that
* can be passed to setUniforms.
* @param modules
* @returns
*/
function assembleGetUniforms(modules) {
	return function getUniforms(opts) {
		const uniforms = {};
		for (const module of modules) {
			const moduleUniforms = module.getUniforms?.(opts, uniforms);
			Object.assign(uniforms, moduleUniforms);
		}
		return uniforms;
	};
}
/**
* NOTE: Removed as id injection defeated caching of shaders
*
* Generate "glslify-compatible" SHADER_NAME defines
* These are understood by the GLSL error parsing function
* If id is provided and no SHADER_NAME constant is present in source, create one
unction getShaderNameDefine(options: {
id?: string;
source: string;
stage: 'vertex' | 'fragment';
}): string {
const {id, source, stage} = options;
const injectShaderName = id && source.indexOf('SHADER_NAME') === -1;
return injectShaderName
? `
#define SHADER_NAME ${id}_${stage}`
: '';
}
*/
/** Generates application defines from an object of key value pairs */
function getApplicationDefines(defines = {}) {
	let sourceText = "";
	for (const define in defines) {
		const value = defines[define];
		if (value || Number.isFinite(value)) sourceText += `#define ${define.toUpperCase()} ${defines[define]}\n`;
	}
	return sourceText;
}
/** Extracts the source code chunk for the specified shader type from the named shader module */
function getShaderModuleSource(module, stage, log) {
	let moduleSource;
	switch (stage) {
		case "vertex":
			moduleSource = module.vs || "";
			break;
		case "fragment":
			moduleSource = module.fs || "";
			break;
		case "wgsl":
			moduleSource = module.source || "";
			break;
		default: assert$3(false);
	}
	if (!module.name) throw new Error("Shader module must have a name");
	validateShaderModuleUniformLayout(module, stage, { log });
	const moduleName = module.name.toUpperCase().replace(/[^0-9a-z]/gi, "_");
	let source = `\
// ----- MODULE ${module.name} ---------------

`;
	if (stage !== "wgsl") source += `#define MODULE_${moduleName}\n`;
	source += `${moduleSource}\n`;
	return source;
}
function getUsedBindingsByGroupFromApplicationWGSL(source) {
	const usedBindingsByGroup = /* @__PURE__ */ new Map();
	for (const match of getWGSLBindingDeclarationMatches(source, WGSL_EXPLICIT_BINDING_DECLARATION_REGEXES)) {
		const location = Number(match.bindingToken);
		const group = Number(match.groupToken);
		validateApplicationWGSLBinding(group, location, match.name);
		registerUsedBindingLocation(usedBindingsByGroup, group, location, `application binding "${match.name}"`);
	}
	return usedBindingsByGroup;
}
function relocateWGSLApplicationBindings(source) {
	const declarationMatches = getWGSLBindingDeclarationMatches(source, WGSL_BINDING_DECLARATION_REGEXES);
	const usedBindingsByGroup = /* @__PURE__ */ new Map();
	for (const declarationMatch of declarationMatches) {
		if (declarationMatch.bindingToken === "auto") continue;
		const location = Number(declarationMatch.bindingToken);
		const group = Number(declarationMatch.groupToken);
		validateApplicationWGSLBinding(group, location, declarationMatch.name);
		registerUsedBindingLocation(usedBindingsByGroup, group, location, `application binding "${declarationMatch.name}"`);
	}
	const relocationState = { sawSupportedBindingDeclaration: declarationMatches.length > 0 };
	const relocatedSource = replaceWGSLBindingDeclarationMatches(source, WGSL_BINDING_DECLARATION_REGEXES, (declarationMatch) => relocateWGSLApplicationBindingMatch(declarationMatch, usedBindingsByGroup, relocationState));
	if (hasWGSLAutoBinding(source) && !relocationState.sawSupportedBindingDeclaration) throw new Error("Unsupported @binding(auto) declaration form in application WGSL. Use adjacent \"@group(N)\" and \"@binding(auto)\" decorators followed by a bindable \"var\" declaration.");
	return { source: relocatedSource };
}
function relocateWGSLModuleBindings(moduleSource, module, context) {
	const bindingAssignments = [];
	const relocationState = {
		sawSupportedBindingDeclaration: getWGSLBindingDeclarationMatches(moduleSource, MODULE_WGSL_BINDING_DECLARATION_REGEXES).length > 0,
		nextHintedBindingLocation: typeof module.firstBindingSlot === "number" ? module.firstBindingSlot : null
	};
	const relocatedSource = replaceWGSLBindingDeclarationMatches(moduleSource, MODULE_WGSL_BINDING_DECLARATION_REGEXES, (declarationMatch) => relocateWGSLModuleBindingMatch(declarationMatch, {
		module,
		context,
		bindingAssignments,
		relocationState
	}));
	if (hasWGSLAutoBinding(moduleSource) && !relocationState.sawSupportedBindingDeclaration) throw new Error(`Unsupported @binding(auto) declaration form in module "${module.name}". Use adjacent "@group(N)" and "@binding(auto)" decorators followed by a bindable "var" declaration.`);
	return {
		source: relocatedSource,
		bindingAssignments
	};
}
function relocateWGSLModuleBindingMatch(declarationMatch, params) {
	const { module, context, bindingAssignments, relocationState } = params;
	const { match, bindingToken, groupToken, name } = declarationMatch;
	const group = Number(groupToken);
	if (bindingToken === "auto") {
		const registryKey = getBindingRegistryKey(group, module.name, name);
		const registryLocation = context.bindingRegistry?.get(registryKey);
		const location = registryLocation !== void 0 ? registryLocation : relocationState.nextHintedBindingLocation === null ? allocateAutoBindingLocation(group, context.usedBindingsByGroup) : allocateAutoBindingLocation(group, context.usedBindingsByGroup, relocationState.nextHintedBindingLocation);
		validateModuleWGSLBinding(module.name, group, location, name);
		if (registryLocation !== void 0 && claimReservedBindingLocation(context.reservedBindingKeysByGroup, group, location, registryKey)) {
			bindingAssignments.push({
				moduleName: module.name,
				name,
				group,
				location
			});
			return match.replace(/@binding\(\s*auto\s*\)/, `@binding(${location})`);
		}
		registerUsedBindingLocation(context.usedBindingsByGroup, group, location, `module "${module.name}" binding "${name}"`);
		context.bindingRegistry?.set(registryKey, location);
		bindingAssignments.push({
			moduleName: module.name,
			name,
			group,
			location
		});
		if (relocationState.nextHintedBindingLocation !== null && registryLocation === void 0) relocationState.nextHintedBindingLocation = location + 1;
		return match.replace(/@binding\(\s*auto\s*\)/, `@binding(${location})`);
	}
	const location = Number(bindingToken);
	validateModuleWGSLBinding(module.name, group, location, name);
	registerUsedBindingLocation(context.usedBindingsByGroup, group, location, `module "${module.name}" binding "${name}"`);
	bindingAssignments.push({
		moduleName: module.name,
		name,
		group,
		location
	});
	return match;
}
function relocateWGSLApplicationBindingMatch(declarationMatch, usedBindingsByGroup, relocationState) {
	const { match, bindingToken, groupToken, name } = declarationMatch;
	const group = Number(groupToken);
	if (bindingToken === "auto") {
		const location = allocateApplicationAutoBindingLocation(group, usedBindingsByGroup);
		validateApplicationWGSLBinding(group, location, name);
		registerUsedBindingLocation(usedBindingsByGroup, group, location, `application binding "${name}"`);
		return match.replace(/@binding\(\s*auto\s*\)/, `@binding(${location})`);
	}
	relocationState.sawSupportedBindingDeclaration = true;
	return match;
}
function reserveRegisteredModuleBindings(modules, bindingRegistry, usedBindingsByGroup) {
	const reservedBindingKeysByGroup = /* @__PURE__ */ new Map();
	if (!bindingRegistry) return reservedBindingKeysByGroup;
	for (const module of modules) for (const binding of getModuleWGSLBindingDeclarations(module)) {
		const registryKey = getBindingRegistryKey(binding.group, module.name, binding.name);
		const location = bindingRegistry.get(registryKey);
		if (location !== void 0) {
			const reservedBindingKeys = reservedBindingKeysByGroup.get(binding.group) || /* @__PURE__ */ new Map();
			const existingReservation = reservedBindingKeys.get(location);
			if (existingReservation && existingReservation !== registryKey) throw new Error(`Duplicate WGSL binding reservation for modules "${existingReservation}" and "${registryKey}": group ${binding.group}, binding ${location}.`);
			registerUsedBindingLocation(usedBindingsByGroup, binding.group, location, `registered module binding "${registryKey}"`);
			reservedBindingKeys.set(location, registryKey);
			reservedBindingKeysByGroup.set(binding.group, reservedBindingKeys);
		}
	}
	return reservedBindingKeysByGroup;
}
function claimReservedBindingLocation(reservedBindingKeysByGroup, group, location, registryKey) {
	const reservedBindingKeys = reservedBindingKeysByGroup.get(group);
	if (!reservedBindingKeys) return false;
	const reservedKey = reservedBindingKeys.get(location);
	if (!reservedKey) return false;
	if (reservedKey !== registryKey) throw new Error(`Registered module binding "${registryKey}" collided with "${reservedKey}": group ${group}, binding ${location}.`);
	return true;
}
function getModuleWGSLBindingDeclarations(module) {
	const declarations = [];
	const moduleSource = module.source || "";
	for (const match of getWGSLBindingDeclarationMatches(moduleSource, MODULE_WGSL_BINDING_DECLARATION_REGEXES)) declarations.push({
		name: match.name,
		group: Number(match.groupToken)
	});
	return declarations;
}
function validateApplicationWGSLBinding(group, location, name) {
	if (group === 0 && location >= RESERVED_APPLICATION_GROUP_0_BINDING_LIMIT) throw new Error(`Application binding "${name}" in group 0 uses reserved binding ${location}. Application-owned explicit group-0 bindings must stay below ${RESERVED_APPLICATION_GROUP_0_BINDING_LIMIT}.`);
}
function validateModuleWGSLBinding(moduleName, group, location, name) {
	if (group === 0 && location < RESERVED_APPLICATION_GROUP_0_BINDING_LIMIT) throw new Error(`Module "${moduleName}" binding "${name}" in group 0 uses reserved application binding ${location}. Module-owned explicit group-0 bindings must be ${RESERVED_APPLICATION_GROUP_0_BINDING_LIMIT} or higher.`);
}
function registerUsedBindingLocation(usedBindingsByGroup, group, location, label) {
	const usedBindings = usedBindingsByGroup.get(group) || /* @__PURE__ */ new Set();
	if (usedBindings.has(location)) throw new Error(`Duplicate WGSL binding assignment for ${label}: group ${group}, binding ${location}.`);
	usedBindings.add(location);
	usedBindingsByGroup.set(group, usedBindings);
}
function allocateAutoBindingLocation(group, usedBindingsByGroup, preferredBindingLocation) {
	const usedBindings = usedBindingsByGroup.get(group) || /* @__PURE__ */ new Set();
	let nextBinding = preferredBindingLocation ?? (group === 0 ? RESERVED_APPLICATION_GROUP_0_BINDING_LIMIT : usedBindings.size > 0 ? Math.max(...usedBindings) + 1 : 0);
	while (usedBindings.has(nextBinding)) nextBinding++;
	return nextBinding;
}
function allocateApplicationAutoBindingLocation(group, usedBindingsByGroup) {
	const usedBindings = usedBindingsByGroup.get(group) || /* @__PURE__ */ new Set();
	let nextBinding = 0;
	while (usedBindings.has(nextBinding)) nextBinding++;
	return nextBinding;
}
function assertNoUnresolvedAutoBindings(source) {
	const unresolvedBinding = getFirstWGSLAutoBindingDeclarationMatch(source, MODULE_WGSL_BINDING_DECLARATION_REGEXES);
	if (!unresolvedBinding) return;
	const moduleName = getWGSLModuleNameAtIndex(source, unresolvedBinding.index);
	if (moduleName) throw new Error(`Unresolved @binding(auto) for module "${moduleName}" binding "${unresolvedBinding.name}" remained in assembled WGSL source.`);
	if (isInApplicationWGSLSection(source, unresolvedBinding.index)) throw new Error(`Unresolved @binding(auto) for application binding "${unresolvedBinding.name}" remained in assembled WGSL source.`);
	throw new Error(`Unresolved @binding(auto) remained in assembled WGSL source near "${formatWGSLSourceSnippet(unresolvedBinding.match)}".`);
}
function formatWGSLBindingAssignmentComments(bindingAssignments) {
	if (bindingAssignments.length === 0) return "";
	let source = "// ----- MODULE WGSL BINDING ASSIGNMENTS ---------------\n";
	for (const bindingAssignment of bindingAssignments) source += `// ${bindingAssignment.moduleName}.${bindingAssignment.name} -> @group(${bindingAssignment.group}) @binding(${bindingAssignment.location})\n`;
	source += "\n";
	return source;
}
function getBindingRegistryKey(group, moduleName, bindingName) {
	return `${group}:${moduleName}:${bindingName}`;
}
function getWGSLModuleNameAtIndex(source, index) {
	const moduleHeaderRegex = /^\/\/ ----- MODULE ([^\n]+) ---------------$/gm;
	let moduleName;
	let match;
	match = moduleHeaderRegex.exec(source);
	while (match && match.index <= index) {
		moduleName = match[1];
		match = moduleHeaderRegex.exec(source);
	}
	return moduleName;
}
function isInApplicationWGSLSection(source, index) {
	const injectionMarkerIndex = source.indexOf(INJECT_SHADER_DECLARATIONS);
	return injectionMarkerIndex >= 0 ? index > injectionMarkerIndex : true;
}
function formatWGSLSourceSnippet(source) {
	return source.replace(/\s+/g, " ").trim();
}
//#endregion
//#region node_modules/@luma.gl/shadertools/dist/lib/preprocessor/preprocessor.js
var DEFINE_NAME_PATTERN = "([a-zA-Z_][a-zA-Z0-9_]*)";
var IFDEF_REGEXP = new RegExp(`^\\s*\\#\\s*ifdef\\s*${DEFINE_NAME_PATTERN}\\s*$`);
var IFNDEF_REGEXP = new RegExp(`^\\s*\\#\\s*ifndef\\s*${DEFINE_NAME_PATTERN}\\s*(?:\\/\\/.*)?$`);
var ELSE_REGEXP = /^\s*\#\s*else\s*(?:\/\/.*)?$/;
var ENDIF_REGEXP = /^\s*\#\s*endif\s*$/;
var IFDEF_WITH_COMMENT_REGEXP = new RegExp(`^\\s*\\#\\s*ifdef\\s*${DEFINE_NAME_PATTERN}\\s*(?:\\/\\/.*)?$`);
var ENDIF_WITH_COMMENT_REGEXP = /^\s*\#\s*endif\s*(?:\/\/.*)?$/;
function preprocess(source, options) {
	const lines = source.split("\n");
	const output = [];
	const conditionalStack = [];
	let conditional = true;
	for (const line of lines) {
		const matchIf = line.match(IFDEF_WITH_COMMENT_REGEXP) || line.match(IFDEF_REGEXP);
		const matchIfNot = line.match(IFNDEF_REGEXP);
		const matchElse = line.match(ELSE_REGEXP);
		const matchEnd = line.match(ENDIF_WITH_COMMENT_REGEXP) || line.match(ENDIF_REGEXP);
		if (matchIf || matchIfNot) {
			const defineName = (matchIf || matchIfNot)?.[1];
			const defineValue = Boolean(options?.defines?.[defineName]);
			const branchTaken = matchIf ? defineValue : !defineValue;
			const active = conditional && branchTaken;
			conditionalStack.push({
				parentActive: conditional,
				branchTaken,
				active
			});
			conditional = active;
		} else if (matchElse) {
			const currentConditional = conditionalStack[conditionalStack.length - 1];
			if (!currentConditional) throw new Error("Encountered #else without matching #ifdef or #ifndef");
			currentConditional.active = currentConditional.parentActive && !currentConditional.branchTaken;
			currentConditional.branchTaken = true;
			conditional = currentConditional.active;
		} else if (matchEnd) {
			conditionalStack.pop();
			conditional = conditionalStack.length ? conditionalStack[conditionalStack.length - 1].active : true;
		} else if (conditional) output.push(line);
	}
	if (conditionalStack.length > 0) throw new Error("Unterminated conditional block in shader source");
	return output.join("\n");
}
//#endregion
//#region node_modules/@luma.gl/shadertools/dist/lib/shader-assembler.js
/**
* A stateful version of `assembleShaders` that can be used to assemble shaders.
* Supports setting of default modules and hooks.
*/
var ShaderAssembler = class ShaderAssembler {
	/** Default ShaderAssembler instance */
	static defaultShaderAssembler;
	/** Hook functions */
	_hookFunctions = [];
	/** Shader modules */
	_defaultModules = [];
	/** Stable per-run WGSL auto-binding assignments keyed by group/module/binding. */
	_wgslBindingRegistry = /* @__PURE__ */ new Map();
	/**
	* A default shader assembler instance - the natural place to register default modules and hooks
	* @returns
	*/
	static getDefaultShaderAssembler() {
		ShaderAssembler.defaultShaderAssembler = ShaderAssembler.defaultShaderAssembler || new ShaderAssembler();
		return ShaderAssembler.defaultShaderAssembler;
	}
	/**
	* Add a default module that does not have to be provided with every call to assembleShaders()
	*/
	addDefaultModule(module) {
		if (!this._defaultModules.find((m) => m.name === (typeof module === "string" ? module : module.name))) this._defaultModules.push(module);
	}
	/**
	* Remove a default module
	*/
	removeDefaultModule(module) {
		const moduleName = typeof module === "string" ? module : module.name;
		this._defaultModules = this._defaultModules.filter((m) => m.name !== moduleName);
	}
	/**
	* Register a shader hook
	* @param hook
	* @param opts
	*/
	addShaderHook(hook, opts) {
		if (opts) hook = Object.assign(opts, { hook });
		this._hookFunctions.push(hook);
	}
	/**
	* Assemble a WGSL unified shader
	* @param platformInfo
	* @param props
	* @returns
	*/
	assembleWGSLShader(props) {
		const modules = this._getModuleList(props.modules);
		const hookFunctions = this._hookFunctions;
		const { source, getUniforms, bindingAssignments } = assembleWGSLShader({
			...props,
			source: props.source,
			_bindingRegistry: this._wgslBindingRegistry,
			modules,
			hookFunctions
		});
		const defines = {
			...modules.reduce((accumulator, module) => {
				Object.assign(accumulator, module.defines);
				return accumulator;
			}, {}),
			...props.defines
		};
		const preprocessedSource = props.platformInfo.shaderLanguage === "wgsl" ? preprocess(source, { defines }) : source;
		return {
			source: preprocessedSource,
			getUniforms,
			modules,
			bindingAssignments,
			bindingTable: getShaderBindingDebugRowsFromWGSL(preprocessedSource, bindingAssignments)
		};
	}
	/**
	* Assemble a pair of shaders into a single shader program
	* @param platformInfo
	* @param props
	* @returns
	*/
	assembleGLSLShaderPair(props) {
		const modules = this._getModuleList(props.modules);
		const hookFunctions = this._hookFunctions;
		return {
			...assembleGLSLShaderPair({
				...props,
				vs: props.vs,
				fs: props.fs,
				modules,
				hookFunctions
			}),
			modules
		};
	}
	/**
	* Dedupe and combine with default modules
	*/
	_getModuleList(appModules = []) {
		const modules = new Array(this._defaultModules.length + appModules.length);
		const seen = {};
		let count = 0;
		for (let i = 0, len = this._defaultModules.length; i < len; ++i) {
			const module = this._defaultModules[i];
			const name = module.name;
			modules[count++] = module;
			seen[name] = true;
		}
		for (let i = 0, len = appModules.length; i < len; ++i) {
			const module = appModules[i];
			const name = module.name;
			if (!seen[name]) {
				modules[count++] = module;
				seen[name] = true;
			}
		}
		modules.length = count;
		initializeShaderModules(modules);
		return modules;
	}
};
1 / Math.PI * 180;
1 / 180 * Math.PI;
globalThis.mathgl = globalThis.mathgl || { config: {
	EPSILON: 1e-12,
	debug: false,
	precision: 4,
	printTypes: false,
	printDegrees: false,
	printRowMajor: true,
	_cartographicRadians: false
} };
var config = globalThis.mathgl.config;
/**
* Formats a value into a string
* @param value
* @param param1
* @returns
*/
function formatValue(value, { precision = config.precision } = {}) {
	value = round(value);
	return `${parseFloat(value.toPrecision(precision))}`;
}
/**
* Check if value is an "array"
* Returns `true` if value is either an array or a typed array
* Note: returns `false` for `ArrayBuffer` and `DataView` instances
* @note isTypedArray and isNumericArray are often more useful in TypeScript
*/
function isArray(value) {
	return Array.isArray(value) || ArrayBuffer.isView(value) && !(value instanceof DataView);
}
function clamp$1(value, min, max) {
	return map(value, (value) => Math.max(min, Math.min(max, value)));
}
function lerp$2(a, b, t) {
	if (isArray(a)) return a.map((ai, i) => lerp$2(ai, b[i], t));
	return t * b + (1 - t) * a;
}
/**
* Compares any two math objects, using `equals` method if available.
* @param a
* @param b
* @param epsilon
* @returns
*/
function equals(a, b, epsilon) {
	const oldEpsilon = config.EPSILON;
	if (epsilon) config.EPSILON = epsilon;
	try {
		if (a === b) return true;
		if (isArray(a) && isArray(b)) {
			if (a.length !== b.length) return false;
			for (let i = 0; i < a.length; ++i) if (!equals(a[i], b[i])) return false;
			return true;
		}
		if (a && a.equals) return a.equals(b);
		if (b && b.equals) return b.equals(a);
		if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) <= config.EPSILON * Math.max(1, Math.abs(a), Math.abs(b));
		return false;
	} finally {
		config.EPSILON = oldEpsilon;
	}
}
function round(value) {
	return Math.round(value / config.EPSILON) * config.EPSILON;
}
function duplicateArray(array) {
	return array.clone ? array.clone() : new Array(array.length);
}
function map(value, func, result) {
	if (isArray(value)) {
		const array = value;
		result = result || duplicateArray(array);
		for (let i = 0; i < result.length && i < array.length; ++i) {
			const val = typeof value === "number" ? value : value[i];
			result[i] = func(val, i, result);
		}
		return result;
	}
	return func(value);
}
//#endregion
//#region node_modules/@math.gl/core/dist/classes/base/math-array.js
/** Base class for vectors and matrices */
var MathArray = class extends Array {
	/**
	* Clone the current object
	* @returns a new copy of this object
	*/
	clone() {
		return new this.constructor().copy(this);
	}
	fromArray(array, offset = 0) {
		for (let i = 0; i < this.ELEMENTS; ++i) this[i] = array[i + offset];
		return this.check();
	}
	toArray(targetArray = [], offset = 0) {
		for (let i = 0; i < this.ELEMENTS; ++i) targetArray[offset + i] = this[i];
		return targetArray;
	}
	toObject(targetObject) {
		return targetObject;
	}
	from(arrayOrObject) {
		return Array.isArray(arrayOrObject) ? this.copy(arrayOrObject) : this.fromObject(arrayOrObject);
	}
	to(arrayOrObject) {
		if (arrayOrObject === this) return this;
		return isArray(arrayOrObject) ? this.toArray(arrayOrObject) : this.toObject(arrayOrObject);
	}
	toTarget(target) {
		return target ? this.to(target) : this;
	}
	/** @deprecated */
	toFloat32Array() {
		return new Float32Array(this);
	}
	toString() {
		return this.formatString(config);
	}
	/** Formats string according to options */
	formatString(opts) {
		let string = "";
		for (let i = 0; i < this.ELEMENTS; ++i) string += (i > 0 ? ", " : "") + formatValue(this[i], opts);
		return `${opts.printTypes ? this.constructor.name : ""}[${string}]`;
	}
	equals(array) {
		if (!array || this.length !== array.length) return false;
		for (let i = 0; i < this.ELEMENTS; ++i) if (!equals(this[i], array[i])) return false;
		return true;
	}
	exactEquals(array) {
		if (!array || this.length !== array.length) return false;
		for (let i = 0; i < this.ELEMENTS; ++i) if (this[i] !== array[i]) return false;
		return true;
	}
	/** Negates all values in this object */
	negate() {
		for (let i = 0; i < this.ELEMENTS; ++i) this[i] = -this[i];
		return this.check();
	}
	lerp(a, b, t) {
		if (t === void 0) return this.lerp(this, a, b);
		for (let i = 0; i < this.ELEMENTS; ++i) {
			const ai = a[i];
			const endValue = typeof b === "number" ? b : b[i];
			this[i] = ai + t * (endValue - ai);
		}
		return this.check();
	}
	/** Minimal */
	min(vector) {
		for (let i = 0; i < this.ELEMENTS; ++i) this[i] = Math.min(vector[i], this[i]);
		return this.check();
	}
	/** Maximal */
	max(vector) {
		for (let i = 0; i < this.ELEMENTS; ++i) this[i] = Math.max(vector[i], this[i]);
		return this.check();
	}
	clamp(minVector, maxVector) {
		for (let i = 0; i < this.ELEMENTS; ++i) this[i] = Math.min(Math.max(this[i], minVector[i]), maxVector[i]);
		return this.check();
	}
	add(...vectors) {
		for (const vector of vectors) for (let i = 0; i < this.ELEMENTS; ++i) this[i] += vector[i];
		return this.check();
	}
	subtract(...vectors) {
		for (const vector of vectors) for (let i = 0; i < this.ELEMENTS; ++i) this[i] -= vector[i];
		return this.check();
	}
	scale(scale) {
		if (typeof scale === "number") for (let i = 0; i < this.ELEMENTS; ++i) this[i] *= scale;
		else for (let i = 0; i < this.ELEMENTS && i < scale.length; ++i) this[i] *= scale[i];
		return this.check();
	}
	/**
	* Multiplies all elements by `scale`
	* Note: `Matrix4.multiplyByScalar` only scales its 3x3 "minor"
	*/
	multiplyByScalar(scalar) {
		for (let i = 0; i < this.ELEMENTS; ++i) this[i] *= scalar;
		return this.check();
	}
	/** Throws an error if array length is incorrect or contains illegal values */
	check() {
		if (config.debug && !this.validate()) throw new Error(`math.gl: ${this.constructor.name} some fields set to invalid numbers'`);
		return this;
	}
	/** Returns false if the array length is incorrect or contains illegal values */
	validate() {
		let valid = this.length === this.ELEMENTS;
		for (let i = 0; i < this.ELEMENTS; ++i) valid = valid && Number.isFinite(this[i]);
		return valid;
	}
	/** @deprecated */
	sub(a) {
		return this.subtract(a);
	}
	/** @deprecated */
	setScalar(a) {
		for (let i = 0; i < this.ELEMENTS; ++i) this[i] = a;
		return this.check();
	}
	/** @deprecated */
	addScalar(a) {
		for (let i = 0; i < this.ELEMENTS; ++i) this[i] += a;
		return this.check();
	}
	/** @deprecated */
	subScalar(a) {
		return this.addScalar(-a);
	}
	/** @deprecated */
	multiplyScalar(scalar) {
		for (let i = 0; i < this.ELEMENTS; ++i) this[i] *= scalar;
		return this.check();
	}
	/** @deprecated */
	divideScalar(a) {
		return this.multiplyByScalar(1 / a);
	}
	/** @deprecated */
	clampScalar(min, max) {
		for (let i = 0; i < this.ELEMENTS; ++i) this[i] = Math.min(Math.max(this[i], min), max);
		return this.check();
	}
	/** @deprecated */
	get elements() {
		return this;
	}
};
//#endregion
//#region node_modules/@math.gl/core/dist/lib/validators.js
function validateVector(v, length) {
	if (v.length !== length) return false;
	for (let i = 0; i < v.length; ++i) if (!Number.isFinite(v[i])) return false;
	return true;
}
function checkNumber(value) {
	if (!Number.isFinite(value)) throw new Error(`Invalid number ${JSON.stringify(value)}`);
	return value;
}
function checkVector(v, length, callerName = "") {
	if (config.debug && !validateVector(v, length)) throw new Error(`math.gl: ${callerName} some fields set to invalid numbers'`);
	return v;
}
//#endregion
//#region node_modules/@math.gl/core/dist/lib/assert.js
function assert$2(condition, message) {
	if (!condition) throw new Error(`math.gl assertion ${message}`);
}
//#endregion
//#region node_modules/@math.gl/core/dist/classes/base/vector.js
/** Base class for vectors with at least 2 elements */
var Vector = class extends MathArray {
	get x() {
		return this[0];
	}
	set x(value) {
		this[0] = checkNumber(value);
	}
	get y() {
		return this[1];
	}
	set y(value) {
		this[1] = checkNumber(value);
	}
	/**
	* Returns the length of the vector from the origin to the point described by this vector
	*
	* @note `length` is a reserved word for Arrays, so `v.length()` will return number of elements
	* Instead we provide `len` and `magnitude`
	*/
	len() {
		return Math.sqrt(this.lengthSquared());
	}
	/**
	* Returns the length of the vector from the origin to the point described by this vector
	*/
	magnitude() {
		return this.len();
	}
	/**
	* Returns the squared length of the vector from the origin to the point described by this vector
	*/
	lengthSquared() {
		let length = 0;
		for (let i = 0; i < this.ELEMENTS; ++i) length += this[i] * this[i];
		return length;
	}
	/**
	* Returns the squared length of the vector from the origin to the point described by this vector
	*/
	magnitudeSquared() {
		return this.lengthSquared();
	}
	distance(mathArray) {
		return Math.sqrt(this.distanceSquared(mathArray));
	}
	distanceSquared(mathArray) {
		let length = 0;
		for (let i = 0; i < this.ELEMENTS; ++i) {
			const dist = this[i] - mathArray[i];
			length += dist * dist;
		}
		return checkNumber(length);
	}
	dot(mathArray) {
		let product = 0;
		for (let i = 0; i < this.ELEMENTS; ++i) product += this[i] * mathArray[i];
		return checkNumber(product);
	}
	normalize() {
		const length = this.magnitude();
		if (length !== 0) for (let i = 0; i < this.ELEMENTS; ++i) this[i] /= length;
		return this.check();
	}
	multiply(...vectors) {
		for (const vector of vectors) for (let i = 0; i < this.ELEMENTS; ++i) this[i] *= vector[i];
		return this.check();
	}
	divide(...vectors) {
		for (const vector of vectors) for (let i = 0; i < this.ELEMENTS; ++i) this[i] /= vector[i];
		return this.check();
	}
	lengthSq() {
		return this.lengthSquared();
	}
	distanceTo(vector) {
		return this.distance(vector);
	}
	distanceToSquared(vector) {
		return this.distanceSquared(vector);
	}
	getComponent(i) {
		assert$2(i >= 0 && i < this.ELEMENTS, "index is out of range");
		return checkNumber(this[i]);
	}
	setComponent(i, value) {
		assert$2(i >= 0 && i < this.ELEMENTS, "index is out of range");
		this[i] = value;
		return this.check();
	}
	addVectors(a, b) {
		return this.copy(a).add(b);
	}
	subVectors(a, b) {
		return this.copy(a).subtract(b);
	}
	multiplyVectors(a, b) {
		return this.copy(a).multiply(b);
	}
	addScaledVector(a, b) {
		return this.add(new this.constructor(a).multiplyScalar(b));
	}
};
var ARRAY_TYPE = typeof Float32Array !== "undefined" ? Float32Array : Array;
Math.PI / 180;
//#endregion
//#region node_modules/@math.gl/core/dist/gl-matrix/vec2.js
/**
* 2 Dimensional Vector
* @module vec2
*/
/**
* Creates a new, empty vec2
*
* @returns a new 2D vector
*/
function create$2() {
	const out = new ARRAY_TYPE(2);
	if (ARRAY_TYPE != Float32Array) {
		out[0] = 0;
		out[1] = 0;
	}
	return out;
}
/**
* Adds two vec2's
*
* @param {NumericArray} out the receiving vector
* @param {Readonly<NumericArray>} a the first operand
* @param {Readonly<NumericArray>} b the second operand
* @returns {NumericArray} out
*/
function add(out, a, b) {
	out[0] = a[0] + b[0];
	out[1] = a[1] + b[1];
	return out;
}
/**
* Subtracts vector b from vector a
*
* @param {NumericArray} out the receiving vector
* @param {Readonly<NumericArray>} a the first operand
* @param {Readonly<NumericArray>} b the second operand
* @returns {NumericArray} out
*/
function subtract$1(out, a, b) {
	out[0] = a[0] - b[0];
	out[1] = a[1] - b[1];
	return out;
}
/**
* Negates the components of a vec2
*
* @param {NumericArray} out the receiving vector
* @param {Readonly<NumericArray>} a vector to negate
* @returns {NumericArray} out
*/
function negate$1(out, a) {
	out[0] = -a[0];
	out[1] = -a[1];
	return out;
}
/**
* Performs a linear interpolation between two vec2's
*
* @param {NumericArray} out the receiving vector
* @param {Readonly<NumericArray>} a the first operand
* @param {Readonly<NumericArray>} b the second operand
* @param {Number} t interpolation amount, in the range [0-1], between the two inputs
* @returns {NumericArray} out
*/
function lerp$1(out, a, b, t) {
	const ax = a[0];
	const ay = a[1];
	out[0] = ax + t * (b[0] - ax);
	out[1] = ay + t * (b[1] - ay);
	return out;
}
/**
* Transforms the vec2 with a mat4
* 3rd vector component is implicitly '0'
* 4th vector component is implicitly '1'
*
* @param {NumericArray} out the receiving vector
* @param {Readonly<NumericArray>} a the vector to transform
* @param {ReadonlyMat4} m matrix to transform with
* @returns {NumericArray} out
*/
function transformMat4$2(out, a, m) {
	const x = a[0];
	const y = a[1];
	out[0] = m[0] * x + m[4] * y + m[12];
	out[1] = m[1] * x + m[5] * y + m[13];
	return out;
}
/**
* Alias for {@link vec2.subtract}
* @function
*/
var sub$1 = subtract$1;
(function() {
	const vec = create$2();
	return function(a, stride, offset, count, fn, arg) {
		let i;
		let l;
		if (!stride) stride = 2;
		if (!offset) offset = 0;
		if (count) l = Math.min(count * stride + offset, a.length);
		else l = a.length;
		for (i = offset; i < l; i += stride) {
			vec[0] = a[i];
			vec[1] = a[i + 1];
			fn(vec, vec, arg);
			a[i] = vec[0];
			a[i + 1] = vec[1];
		}
		return a;
	};
})();
//#endregion
//#region node_modules/@math.gl/core/dist/lib/gl-matrix-extras.js
function vec2_transformMat4AsVector(out, a, m) {
	const x = a[0];
	const y = a[1];
	const w = m[3] * x + m[7] * y || 1;
	out[0] = (m[0] * x + m[4] * y) / w;
	out[1] = (m[1] * x + m[5] * y) / w;
	return out;
}
function vec3_transformMat4AsVector(out, a, m) {
	const x = a[0];
	const y = a[1];
	const z = a[2];
	const w = m[3] * x + m[7] * y + m[11] * z || 1;
	out[0] = (m[0] * x + m[4] * y + m[8] * z) / w;
	out[1] = (m[1] * x + m[5] * y + m[9] * z) / w;
	out[2] = (m[2] * x + m[6] * y + m[10] * z) / w;
	return out;
}
function vec3_transformMat2(out, a, m) {
	const x = a[0];
	const y = a[1];
	out[0] = m[0] * x + m[2] * y;
	out[1] = m[1] * x + m[3] * y;
	out[2] = a[2];
	return out;
}
//#endregion
//#region node_modules/@math.gl/core/dist/gl-matrix/vec3.js
/**
* 3 Dimensional Vector
* @module vec3
*/
/**
* Creates a new, empty vec3
*
* @returns {vec3} a new 3D vector
*/
function create$1() {
	const out = new ARRAY_TYPE(3);
	if (ARRAY_TYPE != Float32Array) {
		out[0] = 0;
		out[1] = 0;
		out[2] = 0;
	}
	return out;
}
/**
* Calculates the length of a vec3
*
* @param {ReadonlyVec3} a vector to calculate length of
* @returns {Number} length of a
*/
function length(a) {
	const x = a[0];
	const y = a[1];
	const z = a[2];
	return Math.sqrt(x * x + y * y + z * z);
}
/**
* Subtracts vector b from vector a
*
* @param {vec3} out the receiving vector
* @param {ReadonlyVec3} a the first operand
* @param {ReadonlyVec3} b the second operand
* @returns {vec3} out
*/
function subtract(out, a, b) {
	out[0] = a[0] - b[0];
	out[1] = a[1] - b[1];
	out[2] = a[2] - b[2];
	return out;
}
/**
* Calculates the squared length of a vec3
*
* @param {ReadonlyVec3} a vector to calculate squared length of
* @returns {Number} squared length of a
*/
function squaredLength(a) {
	const x = a[0];
	const y = a[1];
	const z = a[2];
	return x * x + y * y + z * z;
}
/**
* Negates the components of a vec3
*
* @param {vec3} out the receiving vector
* @param {ReadonlyVec3} a vector to negate
* @returns {vec3} out
*/
function negate(out, a) {
	out[0] = -a[0];
	out[1] = -a[1];
	out[2] = -a[2];
	return out;
}
/**
* Calculates the dot product of two vec3's
*
* @param {ReadonlyVec3} a the first operand
* @param {ReadonlyVec3} b the second operand
* @returns {Number} dot product of a and b
*/
function dot(a, b) {
	return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}
/**
* Computes the cross product of two vec3's
*
* @param {vec3} out the receiving vector
* @param {ReadonlyVec3} a the first operand
* @param {ReadonlyVec3} b the second operand
* @returns {vec3} out
*/
function cross(out, a, b) {
	const ax = a[0];
	const ay = a[1];
	const az = a[2];
	const bx = b[0];
	const by = b[1];
	const bz = b[2];
	out[0] = ay * bz - az * by;
	out[1] = az * bx - ax * bz;
	out[2] = ax * by - ay * bx;
	return out;
}
/**
* Performs a linear interpolation between two vec3's
*
* @param {vec3} out the receiving vector
* @param {ReadonlyVec3} a the first operand
* @param {ReadonlyVec3} b the second operand
* @param {Number} t interpolation amount, in the range [0-1], between the two inputs
* @returns {vec3} out
*/
function lerp(out, a, b, t) {
	const ax = a[0];
	const ay = a[1];
	const az = a[2];
	out[0] = ax + t * (b[0] - ax);
	out[1] = ay + t * (b[1] - ay);
	out[2] = az + t * (b[2] - az);
	return out;
}
/**
* Transforms the vec3 with a mat4.
* 4th vector component is implicitly '1'
*
* @param {vec3} out the receiving vector
* @param {ReadonlyVec3} a the vector to transform
* @param {ReadonlyMat4} m matrix to transform with
* @returns {vec3} out
*/
function transformMat4$1(out, a, m) {
	const x = a[0];
	const y = a[1];
	const z = a[2];
	let w = m[3] * x + m[7] * y + m[11] * z + m[15];
	w = w || 1;
	out[0] = (m[0] * x + m[4] * y + m[8] * z + m[12]) / w;
	out[1] = (m[1] * x + m[5] * y + m[9] * z + m[13]) / w;
	out[2] = (m[2] * x + m[6] * y + m[10] * z + m[14]) / w;
	return out;
}
/**
* Transforms the vec3 with a mat3.
*
* @param {vec3} out the receiving vector
* @param {ReadonlyVec3} a the vector to transform
* @param {ReadonlyMat3} m the 3x3 matrix to transform with
* @returns {vec3} out
*/
function transformMat3(out, a, m) {
	const x = a[0];
	const y = a[1];
	const z = a[2];
	out[0] = x * m[0] + y * m[3] + z * m[6];
	out[1] = x * m[1] + y * m[4] + z * m[7];
	out[2] = x * m[2] + y * m[5] + z * m[8];
	return out;
}
/**
* Transforms the vec3 with a quat
* Can also be used for dual quaternions. (Multiply it with the real part)
*
* @param {vec3} out the receiving vector
* @param {ReadonlyVec3} a the vector to transform
* @param {ReadonlyQuat} q quaternion to transform with
* @returns {vec3} out
*/
function transformQuat(out, a, q) {
	const qx = q[0];
	const qy = q[1];
	const qz = q[2];
	const qw = q[3];
	const x = a[0];
	const y = a[1];
	const z = a[2];
	let uvx = qy * z - qz * y;
	let uvy = qz * x - qx * z;
	let uvz = qx * y - qy * x;
	let uuvx = qy * uvz - qz * uvy;
	let uuvy = qz * uvx - qx * uvz;
	let uuvz = qx * uvy - qy * uvx;
	const w2 = qw * 2;
	uvx *= w2;
	uvy *= w2;
	uvz *= w2;
	uuvx *= 2;
	uuvy *= 2;
	uuvz *= 2;
	out[0] = x + uvx + uuvx;
	out[1] = y + uvy + uuvy;
	out[2] = z + uvz + uuvz;
	return out;
}
/**
* Rotate a 3D vector around the x-axis
* @param {vec3} out The receiving vec3
* @param {ReadonlyVec3} a The vec3 point to rotate
* @param {ReadonlyVec3} b The origin of the rotation
* @param {Number} rad The angle of rotation in radians
* @returns {vec3} out
*/
function rotateX$1(out, a, b, rad) {
	const p = [];
	const r = [];
	p[0] = a[0] - b[0];
	p[1] = a[1] - b[1];
	p[2] = a[2] - b[2];
	r[0] = p[0];
	r[1] = p[1] * Math.cos(rad) - p[2] * Math.sin(rad);
	r[2] = p[1] * Math.sin(rad) + p[2] * Math.cos(rad);
	out[0] = r[0] + b[0];
	out[1] = r[1] + b[1];
	out[2] = r[2] + b[2];
	return out;
}
/**
* Rotate a 3D vector around the y-axis
* @param {vec3} out The receiving vec3
* @param {ReadonlyVec3} a The vec3 point to rotate
* @param {ReadonlyVec3} b The origin of the rotation
* @param {Number} rad The angle of rotation in radians
* @returns {vec3} out
*/
function rotateY$1(out, a, b, rad) {
	const p = [];
	const r = [];
	p[0] = a[0] - b[0];
	p[1] = a[1] - b[1];
	p[2] = a[2] - b[2];
	r[0] = p[2] * Math.sin(rad) + p[0] * Math.cos(rad);
	r[1] = p[1];
	r[2] = p[2] * Math.cos(rad) - p[0] * Math.sin(rad);
	out[0] = r[0] + b[0];
	out[1] = r[1] + b[1];
	out[2] = r[2] + b[2];
	return out;
}
/**
* Rotate a 3D vector around the z-axis
* @param {vec3} out The receiving vec3
* @param {ReadonlyVec3} a The vec3 point to rotate
* @param {ReadonlyVec3} b The origin of the rotation
* @param {Number} rad The angle of rotation in radians
* @returns {vec3} out
*/
function rotateZ$1(out, a, b, rad) {
	const p = [];
	const r = [];
	p[0] = a[0] - b[0];
	p[1] = a[1] - b[1];
	p[2] = a[2] - b[2];
	r[0] = p[0] * Math.cos(rad) - p[1] * Math.sin(rad);
	r[1] = p[0] * Math.sin(rad) + p[1] * Math.cos(rad);
	r[2] = p[2];
	out[0] = r[0] + b[0];
	out[1] = r[1] + b[1];
	out[2] = r[2] + b[2];
	return out;
}
/**
* Get the angle between two 3D vectors
* @param {ReadonlyVec3} a The first operand
* @param {ReadonlyVec3} b The second operand
* @returns {Number} The angle in radians
*/
function angle(a, b) {
	const ax = a[0];
	const ay = a[1];
	const az = a[2];
	const bx = b[0];
	const by = b[1];
	const bz = b[2];
	const mag = Math.sqrt((ax * ax + ay * ay + az * az) * (bx * bx + by * by + bz * bz));
	const cosine = mag && dot(a, b) / mag;
	return Math.acos(Math.min(Math.max(cosine, -1), 1));
}
/**
* Alias for {@link vec3.subtract}
* @function
*/
var sub = subtract;
/**
* Alias for {@link vec3.length}
* @function
*/
var len = length;
/**
* Alias for {@link vec3.squaredLength}
* @function
*/
var sqrLen = squaredLength;
(function() {
	const vec = create$1();
	return function(a, stride, offset, count, fn, arg) {
		let i;
		let l;
		if (!stride) stride = 3;
		if (!offset) offset = 0;
		if (count) l = Math.min(count * stride + offset, a.length);
		else l = a.length;
		for (i = offset; i < l; i += stride) {
			vec[0] = a[i];
			vec[1] = a[i + 1];
			vec[2] = a[i + 2];
			fn(vec, vec, arg);
			a[i] = vec[0];
			a[i + 1] = vec[1];
			a[i + 2] = vec[2];
		}
		return a;
	};
})();
//#endregion
//#region node_modules/@math.gl/core/dist/classes/vector3.js
var ORIGIN = [
	0,
	0,
	0
];
var ZERO$1;
/**
* Three-element vector class with common linear algebra operations.
* Subclass of Array<number> meaning that it is highly compatible with other libraries
*/
var Vector3 = class Vector3 extends Vector {
	static get ZERO() {
		if (!ZERO$1) {
			ZERO$1 = new Vector3(0, 0, 0);
			Object.freeze(ZERO$1);
		}
		return ZERO$1;
	}
	/**
	* @class
	* @param x
	* @param y
	* @param z
	*/
	constructor(x = 0, y = 0, z = 0) {
		super(-0, -0, -0);
		if (arguments.length === 1 && isArray(x)) this.copy(x);
		else {
			if (config.debug) {
				checkNumber(x);
				checkNumber(y);
				checkNumber(z);
			}
			this[0] = x;
			this[1] = y;
			this[2] = z;
		}
	}
	set(x, y, z) {
		this[0] = x;
		this[1] = y;
		this[2] = z;
		return this.check();
	}
	copy(array) {
		this[0] = array[0];
		this[1] = array[1];
		this[2] = array[2];
		return this.check();
	}
	fromObject(object) {
		if (config.debug) {
			checkNumber(object.x);
			checkNumber(object.y);
			checkNumber(object.z);
		}
		this[0] = object.x;
		this[1] = object.y;
		this[2] = object.z;
		return this.check();
	}
	toObject(object) {
		object.x = this[0];
		object.y = this[1];
		object.z = this[2];
		return object;
	}
	get ELEMENTS() {
		return 3;
	}
	get z() {
		return this[2];
	}
	set z(value) {
		this[2] = checkNumber(value);
	}
	angle(vector) {
		return angle(this, vector);
	}
	cross(vector) {
		cross(this, this, vector);
		return this.check();
	}
	rotateX({ radians, origin = ORIGIN }) {
		rotateX$1(this, this, origin, radians);
		return this.check();
	}
	rotateY({ radians, origin = ORIGIN }) {
		rotateY$1(this, this, origin, radians);
		return this.check();
	}
	rotateZ({ radians, origin = ORIGIN }) {
		rotateZ$1(this, this, origin, radians);
		return this.check();
	}
	transform(matrix4) {
		return this.transformAsPoint(matrix4);
	}
	transformAsPoint(matrix4) {
		transformMat4$1(this, this, matrix4);
		return this.check();
	}
	transformAsVector(matrix4) {
		vec3_transformMat4AsVector(this, this, matrix4);
		return this.check();
	}
	transformByMatrix3(matrix3) {
		transformMat3(this, this, matrix3);
		return this.check();
	}
	transformByMatrix2(matrix2) {
		vec3_transformMat2(this, this, matrix2);
		return this.check();
	}
	transformByQuaternion(quaternion) {
		transformQuat(this, this, quaternion);
		return this.check();
	}
};
//#endregion
//#region node_modules/@math.gl/core/dist/classes/base/matrix.js
/** Base class for matrices */
var Matrix = class extends MathArray {
	toString() {
		let string = "[";
		if (config.printRowMajor) {
			string += "row-major:";
			for (let row = 0; row < this.RANK; ++row) for (let col = 0; col < this.RANK; ++col) string += ` ${this[col * this.RANK + row]}`;
		} else {
			string += "column-major:";
			for (let i = 0; i < this.ELEMENTS; ++i) string += ` ${this[i]}`;
		}
		string += "]";
		return string;
	}
	getElementIndex(row, col) {
		return col * this.RANK + row;
	}
	getElement(row, col) {
		return this[col * this.RANK + row];
	}
	setElement(row, col, value) {
		this[col * this.RANK + row] = checkNumber(value);
		return this;
	}
	getColumn(columnIndex, result = new Array(this.RANK).fill(-0)) {
		const firstIndex = columnIndex * this.RANK;
		for (let i = 0; i < this.RANK; ++i) result[i] = this[firstIndex + i];
		return result;
	}
	setColumn(columnIndex, columnVector) {
		const firstIndex = columnIndex * this.RANK;
		for (let i = 0; i < this.RANK; ++i) this[firstIndex + i] = columnVector[i];
		return this;
	}
};
//#endregion
//#region node_modules/@math.gl/core/dist/gl-matrix/mat4.js
/**
* Set a mat4 to the identity matrix
*
* @param {mat4} out the receiving matrix
* @returns {mat4} out
*/
function identity(out) {
	out[0] = 1;
	out[1] = 0;
	out[2] = 0;
	out[3] = 0;
	out[4] = 0;
	out[5] = 1;
	out[6] = 0;
	out[7] = 0;
	out[8] = 0;
	out[9] = 0;
	out[10] = 1;
	out[11] = 0;
	out[12] = 0;
	out[13] = 0;
	out[14] = 0;
	out[15] = 1;
	return out;
}
/**
* Transpose the values of a mat4
*
* @param {mat4} out the receiving matrix
* @param {ReadonlyMat4} a the source matrix
* @returns {mat4} out
*/
function transpose(out, a) {
	if (out === a) {
		const a01 = a[1];
		const a02 = a[2];
		const a03 = a[3];
		const a12 = a[6];
		const a13 = a[7];
		const a23 = a[11];
		out[1] = a[4];
		out[2] = a[8];
		out[3] = a[12];
		out[4] = a01;
		out[6] = a[9];
		out[7] = a[13];
		out[8] = a02;
		out[9] = a12;
		out[11] = a[14];
		out[12] = a03;
		out[13] = a13;
		out[14] = a23;
	} else {
		out[0] = a[0];
		out[1] = a[4];
		out[2] = a[8];
		out[3] = a[12];
		out[4] = a[1];
		out[5] = a[5];
		out[6] = a[9];
		out[7] = a[13];
		out[8] = a[2];
		out[9] = a[6];
		out[10] = a[10];
		out[11] = a[14];
		out[12] = a[3];
		out[13] = a[7];
		out[14] = a[11];
		out[15] = a[15];
	}
	return out;
}
/**
* Inverts a mat4
*
* @param {mat4} out the receiving matrix
* @param {ReadonlyMat4} a the source matrix
* @returns {mat4} out
*/
function invert(out, a) {
	const a00 = a[0];
	const a01 = a[1];
	const a02 = a[2];
	const a03 = a[3];
	const a10 = a[4];
	const a11 = a[5];
	const a12 = a[6];
	const a13 = a[7];
	const a20 = a[8];
	const a21 = a[9];
	const a22 = a[10];
	const a23 = a[11];
	const a30 = a[12];
	const a31 = a[13];
	const a32 = a[14];
	const a33 = a[15];
	const b00 = a00 * a11 - a01 * a10;
	const b01 = a00 * a12 - a02 * a10;
	const b02 = a00 * a13 - a03 * a10;
	const b03 = a01 * a12 - a02 * a11;
	const b04 = a01 * a13 - a03 * a11;
	const b05 = a02 * a13 - a03 * a12;
	const b06 = a20 * a31 - a21 * a30;
	const b07 = a20 * a32 - a22 * a30;
	const b08 = a20 * a33 - a23 * a30;
	const b09 = a21 * a32 - a22 * a31;
	const b10 = a21 * a33 - a23 * a31;
	const b11 = a22 * a33 - a23 * a32;
	let det = b00 * b11 - b01 * b10 + b02 * b09 + b03 * b08 - b04 * b07 + b05 * b06;
	if (!det) return null;
	det = 1 / det;
	out[0] = (a11 * b11 - a12 * b10 + a13 * b09) * det;
	out[1] = (a02 * b10 - a01 * b11 - a03 * b09) * det;
	out[2] = (a31 * b05 - a32 * b04 + a33 * b03) * det;
	out[3] = (a22 * b04 - a21 * b05 - a23 * b03) * det;
	out[4] = (a12 * b08 - a10 * b11 - a13 * b07) * det;
	out[5] = (a00 * b11 - a02 * b08 + a03 * b07) * det;
	out[6] = (a32 * b02 - a30 * b05 - a33 * b01) * det;
	out[7] = (a20 * b05 - a22 * b02 + a23 * b01) * det;
	out[8] = (a10 * b10 - a11 * b08 + a13 * b06) * det;
	out[9] = (a01 * b08 - a00 * b10 - a03 * b06) * det;
	out[10] = (a30 * b04 - a31 * b02 + a33 * b00) * det;
	out[11] = (a21 * b02 - a20 * b04 - a23 * b00) * det;
	out[12] = (a11 * b07 - a10 * b09 - a12 * b06) * det;
	out[13] = (a00 * b09 - a01 * b07 + a02 * b06) * det;
	out[14] = (a31 * b01 - a30 * b03 - a32 * b00) * det;
	out[15] = (a20 * b03 - a21 * b01 + a22 * b00) * det;
	return out;
}
/**
* Calculates the determinant of a mat4
*
* @param {ReadonlyMat4} a the source matrix
* @returns {Number} determinant of a
*/
function determinant(a) {
	const a00 = a[0];
	const a01 = a[1];
	const a02 = a[2];
	const a03 = a[3];
	const a10 = a[4];
	const a11 = a[5];
	const a12 = a[6];
	const a13 = a[7];
	const a20 = a[8];
	const a21 = a[9];
	const a22 = a[10];
	const a23 = a[11];
	const a30 = a[12];
	const a31 = a[13];
	const a32 = a[14];
	const a33 = a[15];
	const b0 = a00 * a11 - a01 * a10;
	const b1 = a00 * a12 - a02 * a10;
	const b2 = a01 * a12 - a02 * a11;
	const b3 = a20 * a31 - a21 * a30;
	const b4 = a20 * a32 - a22 * a30;
	const b5 = a21 * a32 - a22 * a31;
	const b6 = a00 * b5 - a01 * b4 + a02 * b3;
	const b7 = a10 * b5 - a11 * b4 + a12 * b3;
	const b8 = a20 * b2 - a21 * b1 + a22 * b0;
	const b9 = a30 * b2 - a31 * b1 + a32 * b0;
	return a13 * b6 - a03 * b7 + a33 * b8 - a23 * b9;
}
/**
* Multiplies two mat4s
*
* @param {mat4} out the receiving matrix
* @param {ReadonlyMat4} a the first operand
* @param {ReadonlyMat4} b the second operand
* @returns {mat4} out
*/
function multiply(out, a, b) {
	const a00 = a[0];
	const a01 = a[1];
	const a02 = a[2];
	const a03 = a[3];
	const a10 = a[4];
	const a11 = a[5];
	const a12 = a[6];
	const a13 = a[7];
	const a20 = a[8];
	const a21 = a[9];
	const a22 = a[10];
	const a23 = a[11];
	const a30 = a[12];
	const a31 = a[13];
	const a32 = a[14];
	const a33 = a[15];
	let b0 = b[0];
	let b1 = b[1];
	let b2 = b[2];
	let b3 = b[3];
	out[0] = b0 * a00 + b1 * a10 + b2 * a20 + b3 * a30;
	out[1] = b0 * a01 + b1 * a11 + b2 * a21 + b3 * a31;
	out[2] = b0 * a02 + b1 * a12 + b2 * a22 + b3 * a32;
	out[3] = b0 * a03 + b1 * a13 + b2 * a23 + b3 * a33;
	b0 = b[4];
	b1 = b[5];
	b2 = b[6];
	b3 = b[7];
	out[4] = b0 * a00 + b1 * a10 + b2 * a20 + b3 * a30;
	out[5] = b0 * a01 + b1 * a11 + b2 * a21 + b3 * a31;
	out[6] = b0 * a02 + b1 * a12 + b2 * a22 + b3 * a32;
	out[7] = b0 * a03 + b1 * a13 + b2 * a23 + b3 * a33;
	b0 = b[8];
	b1 = b[9];
	b2 = b[10];
	b3 = b[11];
	out[8] = b0 * a00 + b1 * a10 + b2 * a20 + b3 * a30;
	out[9] = b0 * a01 + b1 * a11 + b2 * a21 + b3 * a31;
	out[10] = b0 * a02 + b1 * a12 + b2 * a22 + b3 * a32;
	out[11] = b0 * a03 + b1 * a13 + b2 * a23 + b3 * a33;
	b0 = b[12];
	b1 = b[13];
	b2 = b[14];
	b3 = b[15];
	out[12] = b0 * a00 + b1 * a10 + b2 * a20 + b3 * a30;
	out[13] = b0 * a01 + b1 * a11 + b2 * a21 + b3 * a31;
	out[14] = b0 * a02 + b1 * a12 + b2 * a22 + b3 * a32;
	out[15] = b0 * a03 + b1 * a13 + b2 * a23 + b3 * a33;
	return out;
}
/**
* Translate a mat4 by the given vector
*
* @param {mat4} out the receiving matrix
* @param {ReadonlyMat4} a the matrix to translate
* @param {ReadonlyVec3} v vector to translate by
* @returns {mat4} out
*/
function translate(out, a, v) {
	const x = v[0];
	const y = v[1];
	const z = v[2];
	let a00;
	let a01;
	let a02;
	let a03;
	let a10;
	let a11;
	let a12;
	let a13;
	let a20;
	let a21;
	let a22;
	let a23;
	if (a === out) {
		out[12] = a[0] * x + a[4] * y + a[8] * z + a[12];
		out[13] = a[1] * x + a[5] * y + a[9] * z + a[13];
		out[14] = a[2] * x + a[6] * y + a[10] * z + a[14];
		out[15] = a[3] * x + a[7] * y + a[11] * z + a[15];
	} else {
		a00 = a[0];
		a01 = a[1];
		a02 = a[2];
		a03 = a[3];
		a10 = a[4];
		a11 = a[5];
		a12 = a[6];
		a13 = a[7];
		a20 = a[8];
		a21 = a[9];
		a22 = a[10];
		a23 = a[11];
		out[0] = a00;
		out[1] = a01;
		out[2] = a02;
		out[3] = a03;
		out[4] = a10;
		out[5] = a11;
		out[6] = a12;
		out[7] = a13;
		out[8] = a20;
		out[9] = a21;
		out[10] = a22;
		out[11] = a23;
		out[12] = a00 * x + a10 * y + a20 * z + a[12];
		out[13] = a01 * x + a11 * y + a21 * z + a[13];
		out[14] = a02 * x + a12 * y + a22 * z + a[14];
		out[15] = a03 * x + a13 * y + a23 * z + a[15];
	}
	return out;
}
/**
* Scales the mat4 by the dimensions in the given vec3 not using vectorization
*
* @param {mat4} out the receiving matrix
* @param {ReadonlyMat4} a the matrix to scale
* @param {ReadonlyVec3} v the vec3 to scale the matrix by
* @returns {mat4} out
**/
function scale$1(out, a, v) {
	const x = v[0];
	const y = v[1];
	const z = v[2];
	out[0] = a[0] * x;
	out[1] = a[1] * x;
	out[2] = a[2] * x;
	out[3] = a[3] * x;
	out[4] = a[4] * y;
	out[5] = a[5] * y;
	out[6] = a[6] * y;
	out[7] = a[7] * y;
	out[8] = a[8] * z;
	out[9] = a[9] * z;
	out[10] = a[10] * z;
	out[11] = a[11] * z;
	out[12] = a[12];
	out[13] = a[13];
	out[14] = a[14];
	out[15] = a[15];
	return out;
}
/**
* Rotates a mat4 by the given angle around the given axis
*
* @param {mat4} out the receiving matrix
* @param {ReadonlyMat4} a the matrix to rotate
* @param {Number} rad the angle to rotate the matrix by
* @param {ReadonlyVec3} axis the axis to rotate around
* @returns {mat4} out
*/
function rotate(out, a, rad, axis) {
	let x = axis[0];
	let y = axis[1];
	let z = axis[2];
	let len = Math.sqrt(x * x + y * y + z * z);
	let c;
	let s;
	let t;
	let a00;
	let a01;
	let a02;
	let a03;
	let a10;
	let a11;
	let a12;
	let a13;
	let a20;
	let a21;
	let a22;
	let a23;
	let b00;
	let b01;
	let b02;
	let b10;
	let b11;
	let b12;
	let b20;
	let b21;
	let b22;
	if (len < 1e-6) return null;
	len = 1 / len;
	x *= len;
	y *= len;
	z *= len;
	s = Math.sin(rad);
	c = Math.cos(rad);
	t = 1 - c;
	a00 = a[0];
	a01 = a[1];
	a02 = a[2];
	a03 = a[3];
	a10 = a[4];
	a11 = a[5];
	a12 = a[6];
	a13 = a[7];
	a20 = a[8];
	a21 = a[9];
	a22 = a[10];
	a23 = a[11];
	b00 = x * x * t + c;
	b01 = y * x * t + z * s;
	b02 = z * x * t - y * s;
	b10 = x * y * t - z * s;
	b11 = y * y * t + c;
	b12 = z * y * t + x * s;
	b20 = x * z * t + y * s;
	b21 = y * z * t - x * s;
	b22 = z * z * t + c;
	out[0] = a00 * b00 + a10 * b01 + a20 * b02;
	out[1] = a01 * b00 + a11 * b01 + a21 * b02;
	out[2] = a02 * b00 + a12 * b01 + a22 * b02;
	out[3] = a03 * b00 + a13 * b01 + a23 * b02;
	out[4] = a00 * b10 + a10 * b11 + a20 * b12;
	out[5] = a01 * b10 + a11 * b11 + a21 * b12;
	out[6] = a02 * b10 + a12 * b11 + a22 * b12;
	out[7] = a03 * b10 + a13 * b11 + a23 * b12;
	out[8] = a00 * b20 + a10 * b21 + a20 * b22;
	out[9] = a01 * b20 + a11 * b21 + a21 * b22;
	out[10] = a02 * b20 + a12 * b21 + a22 * b22;
	out[11] = a03 * b20 + a13 * b21 + a23 * b22;
	if (a !== out) {
		out[12] = a[12];
		out[13] = a[13];
		out[14] = a[14];
		out[15] = a[15];
	}
	return out;
}
/**
* Rotates a matrix by the given angle around the X axis
*
* @param {mat4} out the receiving matrix
* @param {ReadonlyMat4} a the matrix to rotate
* @param {Number} rad the angle to rotate the matrix by
* @returns {mat4} out
*/
function rotateX(out, a, rad) {
	const s = Math.sin(rad);
	const c = Math.cos(rad);
	const a10 = a[4];
	const a11 = a[5];
	const a12 = a[6];
	const a13 = a[7];
	const a20 = a[8];
	const a21 = a[9];
	const a22 = a[10];
	const a23 = a[11];
	if (a !== out) {
		out[0] = a[0];
		out[1] = a[1];
		out[2] = a[2];
		out[3] = a[3];
		out[12] = a[12];
		out[13] = a[13];
		out[14] = a[14];
		out[15] = a[15];
	}
	out[4] = a10 * c + a20 * s;
	out[5] = a11 * c + a21 * s;
	out[6] = a12 * c + a22 * s;
	out[7] = a13 * c + a23 * s;
	out[8] = a20 * c - a10 * s;
	out[9] = a21 * c - a11 * s;
	out[10] = a22 * c - a12 * s;
	out[11] = a23 * c - a13 * s;
	return out;
}
/**
* Rotates a matrix by the given angle around the Y axis
*
* @param {mat4} out the receiving matrix
* @param {ReadonlyMat4} a the matrix to rotate
* @param {Number} rad the angle to rotate the matrix by
* @returns {mat4} out
*/
function rotateY(out, a, rad) {
	const s = Math.sin(rad);
	const c = Math.cos(rad);
	const a00 = a[0];
	const a01 = a[1];
	const a02 = a[2];
	const a03 = a[3];
	const a20 = a[8];
	const a21 = a[9];
	const a22 = a[10];
	const a23 = a[11];
	if (a !== out) {
		out[4] = a[4];
		out[5] = a[5];
		out[6] = a[6];
		out[7] = a[7];
		out[12] = a[12];
		out[13] = a[13];
		out[14] = a[14];
		out[15] = a[15];
	}
	out[0] = a00 * c - a20 * s;
	out[1] = a01 * c - a21 * s;
	out[2] = a02 * c - a22 * s;
	out[3] = a03 * c - a23 * s;
	out[8] = a00 * s + a20 * c;
	out[9] = a01 * s + a21 * c;
	out[10] = a02 * s + a22 * c;
	out[11] = a03 * s + a23 * c;
	return out;
}
/**
* Rotates a matrix by the given angle around the Z axis
*
* @param {mat4} out the receiving matrix
* @param {ReadonlyMat4} a the matrix to rotate
* @param {Number} rad the angle to rotate the matrix by
* @returns {mat4} out
*/
function rotateZ(out, a, rad) {
	const s = Math.sin(rad);
	const c = Math.cos(rad);
	const a00 = a[0];
	const a01 = a[1];
	const a02 = a[2];
	const a03 = a[3];
	const a10 = a[4];
	const a11 = a[5];
	const a12 = a[6];
	const a13 = a[7];
	if (a !== out) {
		out[8] = a[8];
		out[9] = a[9];
		out[10] = a[10];
		out[11] = a[11];
		out[12] = a[12];
		out[13] = a[13];
		out[14] = a[14];
		out[15] = a[15];
	}
	out[0] = a00 * c + a10 * s;
	out[1] = a01 * c + a11 * s;
	out[2] = a02 * c + a12 * s;
	out[3] = a03 * c + a13 * s;
	out[4] = a10 * c - a00 * s;
	out[5] = a11 * c - a01 * s;
	out[6] = a12 * c - a02 * s;
	out[7] = a13 * c - a03 * s;
	return out;
}
/**
* Calculates a 4x4 matrix from the given quaternion
*
* @param {mat4} out mat4 receiving operation result
* @param {ReadonlyQuat} q Quaternion to create matrix from
*
* @returns {mat4} out
*/
function fromQuat(out, q) {
	const x = q[0];
	const y = q[1];
	const z = q[2];
	const w = q[3];
	const x2 = x + x;
	const y2 = y + y;
	const z2 = z + z;
	const xx = x * x2;
	const yx = y * x2;
	const yy = y * y2;
	const zx = z * x2;
	const zy = z * y2;
	const zz = z * z2;
	const wx = w * x2;
	const wy = w * y2;
	const wz = w * z2;
	out[0] = 1 - yy - zz;
	out[1] = yx + wz;
	out[2] = zx - wy;
	out[3] = 0;
	out[4] = yx - wz;
	out[5] = 1 - xx - zz;
	out[6] = zy + wx;
	out[7] = 0;
	out[8] = zx + wy;
	out[9] = zy - wx;
	out[10] = 1 - xx - yy;
	out[11] = 0;
	out[12] = 0;
	out[13] = 0;
	out[14] = 0;
	out[15] = 1;
	return out;
}
/**
* Generates a frustum matrix with the given bounds
*
* @param {mat4} out mat4 frustum matrix will be written into
* @param {Number} left Left bound of the frustum
* @param {Number} right Right bound of the frustum
* @param {Number} bottom Bottom bound of the frustum
* @param {Number} top Top bound of the frustum
* @param {Number} near Near bound of the frustum
* @param {Number} far Far bound of the frustum
* @returns {mat4} out
*/
function frustum(out, left, right, bottom, top, near, far) {
	const rl = 1 / (right - left);
	const tb = 1 / (top - bottom);
	const nf = 1 / (near - far);
	out[0] = near * 2 * rl;
	out[1] = 0;
	out[2] = 0;
	out[3] = 0;
	out[4] = 0;
	out[5] = near * 2 * tb;
	out[6] = 0;
	out[7] = 0;
	out[8] = (right + left) * rl;
	out[9] = (top + bottom) * tb;
	out[10] = (far + near) * nf;
	out[11] = -1;
	out[12] = 0;
	out[13] = 0;
	out[14] = far * near * 2 * nf;
	out[15] = 0;
	return out;
}
/**
* Generates a perspective projection matrix with the given bounds.
* The near/far clip planes correspond to a normalized device coordinate Z range of [-1, 1],
* which matches WebGL/OpenGL's clip volume.
* Passing null/undefined/no value for far will generate infinite projection matrix.
*
* @param {mat4} out mat4 frustum matrix will be written into
* @param {number} fovy Vertical field of view in radians
* @param {number} aspect Aspect ratio. typically viewport width/height
* @param {number} near Near bound of the frustum
* @param {number} far Far bound of the frustum, can be null or Infinity
* @returns {mat4} out
*/
function perspectiveNO(out, fovy, aspect, near, far) {
	const f = 1 / Math.tan(fovy / 2);
	out[0] = f / aspect;
	out[1] = 0;
	out[2] = 0;
	out[3] = 0;
	out[4] = 0;
	out[5] = f;
	out[6] = 0;
	out[7] = 0;
	out[8] = 0;
	out[9] = 0;
	out[11] = -1;
	out[12] = 0;
	out[13] = 0;
	out[15] = 0;
	if (far != null && far !== Infinity) {
		const nf = 1 / (near - far);
		out[10] = (far + near) * nf;
		out[14] = 2 * far * near * nf;
	} else {
		out[10] = -1;
		out[14] = -2 * near;
	}
	return out;
}
/**
* Alias for {@link mat4.perspectiveNO}
* @function
*/
var perspective = perspectiveNO;
/**
* Generates a orthogonal projection matrix with the given bounds.
* The near/far clip planes correspond to a normalized device coordinate Z range of [-1, 1],
* which matches WebGL/OpenGL's clip volume.
*
* @param {mat4} out mat4 frustum matrix will be written into
* @param {number} left Left bound of the frustum
* @param {number} right Right bound of the frustum
* @param {number} bottom Bottom bound of the frustum
* @param {number} top Top bound of the frustum
* @param {number} near Near bound of the frustum
* @param {number} far Far bound of the frustum
* @returns {mat4} out
*/
function orthoNO(out, left, right, bottom, top, near, far) {
	const lr = 1 / (left - right);
	const bt = 1 / (bottom - top);
	const nf = 1 / (near - far);
	out[0] = -2 * lr;
	out[1] = 0;
	out[2] = 0;
	out[3] = 0;
	out[4] = 0;
	out[5] = -2 * bt;
	out[6] = 0;
	out[7] = 0;
	out[8] = 0;
	out[9] = 0;
	out[10] = 2 * nf;
	out[11] = 0;
	out[12] = (left + right) * lr;
	out[13] = (top + bottom) * bt;
	out[14] = (far + near) * nf;
	out[15] = 1;
	return out;
}
/**
* Alias for {@link mat4.orthoNO}
* @function
*/
var ortho = orthoNO;
/**
* Generates a look-at matrix with the given eye position, focal point, and up axis.
* If you want a matrix that actually makes an object look at another object, you should use targetTo instead.
*
* @param {mat4} out mat4 frustum matrix will be written into
* @param {ReadonlyVec3} eye Position of the viewer
* @param {ReadonlyVec3} center Point the viewer is looking at
* @param {ReadonlyVec3} up vec3 pointing up
* @returns {mat4} out
*/
function lookAt(out, eye, center, up) {
	let len;
	let x0;
	let x1;
	let x2;
	let y0;
	let y1;
	let y2;
	let z0;
	let z1;
	let z2;
	const eyex = eye[0];
	const eyey = eye[1];
	const eyez = eye[2];
	const upx = up[0];
	const upy = up[1];
	const upz = up[2];
	const centerx = center[0];
	const centery = center[1];
	const centerz = center[2];
	if (Math.abs(eyex - centerx) < 1e-6 && Math.abs(eyey - centery) < 1e-6 && Math.abs(eyez - centerz) < 1e-6) return identity(out);
	z0 = eyex - centerx;
	z1 = eyey - centery;
	z2 = eyez - centerz;
	len = 1 / Math.sqrt(z0 * z0 + z1 * z1 + z2 * z2);
	z0 *= len;
	z1 *= len;
	z2 *= len;
	x0 = upy * z2 - upz * z1;
	x1 = upz * z0 - upx * z2;
	x2 = upx * z1 - upy * z0;
	len = Math.sqrt(x0 * x0 + x1 * x1 + x2 * x2);
	if (!len) {
		x0 = 0;
		x1 = 0;
		x2 = 0;
	} else {
		len = 1 / len;
		x0 *= len;
		x1 *= len;
		x2 *= len;
	}
	y0 = z1 * x2 - z2 * x1;
	y1 = z2 * x0 - z0 * x2;
	y2 = z0 * x1 - z1 * x0;
	len = Math.sqrt(y0 * y0 + y1 * y1 + y2 * y2);
	if (!len) {
		y0 = 0;
		y1 = 0;
		y2 = 0;
	} else {
		len = 1 / len;
		y0 *= len;
		y1 *= len;
		y2 *= len;
	}
	out[0] = x0;
	out[1] = y0;
	out[2] = z0;
	out[3] = 0;
	out[4] = x1;
	out[5] = y1;
	out[6] = z1;
	out[7] = 0;
	out[8] = x2;
	out[9] = y2;
	out[10] = z2;
	out[11] = 0;
	out[12] = -(x0 * eyex + x1 * eyey + x2 * eyez);
	out[13] = -(y0 * eyex + y1 * eyey + y2 * eyez);
	out[14] = -(z0 * eyex + z1 * eyey + z2 * eyez);
	out[15] = 1;
	return out;
}
//#endregion
//#region node_modules/@math.gl/core/dist/gl-matrix/vec4.js
/**
* 4 Dimensional Vector
* @module vec4
*/
/**
* Creates a new, empty vec4
*
* @returns {vec4} a new 4D vector
*/
function create() {
	const out = new ARRAY_TYPE(4);
	if (ARRAY_TYPE != Float32Array) {
		out[0] = 0;
		out[1] = 0;
		out[2] = 0;
		out[3] = 0;
	}
	return out;
}
/**
* Scales a vec4 by a scalar number
*
* @param {vec4} out the receiving vector
* @param {ReadonlyVec4} a the vector to scale
* @param {Number} b amount to scale the vector by
* @returns {vec4} out
*/
function scale(out, a, b) {
	out[0] = a[0] * b;
	out[1] = a[1] * b;
	out[2] = a[2] * b;
	out[3] = a[3] * b;
	return out;
}
/**
* Transforms the vec4 with a mat4.
*
* @param {vec4} out the receiving vector
* @param {ReadonlyVec4} a the vector to transform
* @param {ReadonlyMat4} m matrix to transform with
* @returns {vec4} out
*/
function transformMat4(out, a, m) {
	const x = a[0];
	const y = a[1];
	const z = a[2];
	const w = a[3];
	out[0] = m[0] * x + m[4] * y + m[8] * z + m[12] * w;
	out[1] = m[1] * x + m[5] * y + m[9] * z + m[13] * w;
	out[2] = m[2] * x + m[6] * y + m[10] * z + m[14] * w;
	out[3] = m[3] * x + m[7] * y + m[11] * z + m[15] * w;
	return out;
}
(function() {
	const vec = create();
	return function(a, stride, offset, count, fn, arg) {
		let i;
		let l;
		if (!stride) stride = 4;
		if (!offset) offset = 0;
		if (count) l = Math.min(count * stride + offset, a.length);
		else l = a.length;
		for (i = offset; i < l; i += stride) {
			vec[0] = a[i];
			vec[1] = a[i + 1];
			vec[2] = a[i + 2];
			vec[3] = a[i + 3];
			fn(vec, vec, arg);
			a[i] = vec[0];
			a[i + 1] = vec[1];
			a[i + 2] = vec[2];
			a[i + 3] = vec[3];
		}
		return a;
	};
})();
//#endregion
//#region node_modules/@math.gl/core/dist/classes/matrix4.js
var INDICES;
(function(INDICES) {
	INDICES[INDICES["COL0ROW0"] = 0] = "COL0ROW0";
	INDICES[INDICES["COL0ROW1"] = 1] = "COL0ROW1";
	INDICES[INDICES["COL0ROW2"] = 2] = "COL0ROW2";
	INDICES[INDICES["COL0ROW3"] = 3] = "COL0ROW3";
	INDICES[INDICES["COL1ROW0"] = 4] = "COL1ROW0";
	INDICES[INDICES["COL1ROW1"] = 5] = "COL1ROW1";
	INDICES[INDICES["COL1ROW2"] = 6] = "COL1ROW2";
	INDICES[INDICES["COL1ROW3"] = 7] = "COL1ROW3";
	INDICES[INDICES["COL2ROW0"] = 8] = "COL2ROW0";
	INDICES[INDICES["COL2ROW1"] = 9] = "COL2ROW1";
	INDICES[INDICES["COL2ROW2"] = 10] = "COL2ROW2";
	INDICES[INDICES["COL2ROW3"] = 11] = "COL2ROW3";
	INDICES[INDICES["COL3ROW0"] = 12] = "COL3ROW0";
	INDICES[INDICES["COL3ROW1"] = 13] = "COL3ROW1";
	INDICES[INDICES["COL3ROW2"] = 14] = "COL3ROW2";
	INDICES[INDICES["COL3ROW3"] = 15] = "COL3ROW3";
})(INDICES || (INDICES = {}));
var DEFAULT_FOVY = 45 * Math.PI / 180;
var DEFAULT_ASPECT = 1;
var DEFAULT_NEAR = .1;
var DEFAULT_FAR = 500;
var IDENTITY_MATRIX$1 = Object.freeze([
	1,
	0,
	0,
	0,
	0,
	1,
	0,
	0,
	0,
	0,
	1,
	0,
	0,
	0,
	0,
	1
]);
/**
* A 4x4 matrix with common linear algebra operations
* Subclass of Array<number> meaning that it is highly compatible with other libraries
*/
var Matrix4 = class extends Matrix {
	static get IDENTITY() {
		return getIdentityMatrix();
	}
	static get ZERO() {
		return getZeroMatrix();
	}
	get ELEMENTS() {
		return 16;
	}
	get RANK() {
		return 4;
	}
	get INDICES() {
		return INDICES;
	}
	constructor(array) {
		super(-0, -0, -0, -0, -0, -0, -0, -0, -0, -0, -0, -0, -0, -0, -0, -0);
		if (arguments.length === 1 && Array.isArray(array)) this.copy(array);
		else this.identity();
	}
	copy(array) {
		this[0] = array[0];
		this[1] = array[1];
		this[2] = array[2];
		this[3] = array[3];
		this[4] = array[4];
		this[5] = array[5];
		this[6] = array[6];
		this[7] = array[7];
		this[8] = array[8];
		this[9] = array[9];
		this[10] = array[10];
		this[11] = array[11];
		this[12] = array[12];
		this[13] = array[13];
		this[14] = array[14];
		this[15] = array[15];
		return this.check();
	}
	set(m00, m10, m20, m30, m01, m11, m21, m31, m02, m12, m22, m32, m03, m13, m23, m33) {
		this[0] = m00;
		this[1] = m10;
		this[2] = m20;
		this[3] = m30;
		this[4] = m01;
		this[5] = m11;
		this[6] = m21;
		this[7] = m31;
		this[8] = m02;
		this[9] = m12;
		this[10] = m22;
		this[11] = m32;
		this[12] = m03;
		this[13] = m13;
		this[14] = m23;
		this[15] = m33;
		return this.check();
	}
	setRowMajor(m00, m01, m02, m03, m10, m11, m12, m13, m20, m21, m22, m23, m30, m31, m32, m33) {
		this[0] = m00;
		this[1] = m10;
		this[2] = m20;
		this[3] = m30;
		this[4] = m01;
		this[5] = m11;
		this[6] = m21;
		this[7] = m31;
		this[8] = m02;
		this[9] = m12;
		this[10] = m22;
		this[11] = m32;
		this[12] = m03;
		this[13] = m13;
		this[14] = m23;
		this[15] = m33;
		return this.check();
	}
	toRowMajor(result) {
		result[0] = this[0];
		result[1] = this[4];
		result[2] = this[8];
		result[3] = this[12];
		result[4] = this[1];
		result[5] = this[5];
		result[6] = this[9];
		result[7] = this[13];
		result[8] = this[2];
		result[9] = this[6];
		result[10] = this[10];
		result[11] = this[14];
		result[12] = this[3];
		result[13] = this[7];
		result[14] = this[11];
		result[15] = this[15];
		return result;
	}
	/** Set to identity matrix */
	identity() {
		return this.copy(IDENTITY_MATRIX$1);
	}
	/**
	*
	* @param object
	* @returns self
	*/
	fromObject(object) {
		return this.check();
	}
	/**
	* Calculates a 4x4 matrix from the given quaternion
	* @param quaternion Quaternion to create matrix from
	* @returns self
	*/
	fromQuaternion(quaternion) {
		fromQuat(this, quaternion);
		return this.check();
	}
	/**
	* Generates a frustum matrix with the given bounds
	* @param view.left - Left bound of the frustum
	* @param view.right - Right bound of the frustum
	* @param view.bottom - Bottom bound of the frustum
	* @param view.top - Top bound of the frustum
	* @param view.near - Near bound of the frustum
	* @param view.far - Far bound of the frustum. Can be set to Infinity.
	* @returns self
	*/
	frustum(view) {
		const { left, right, bottom, top, near = DEFAULT_NEAR, far = DEFAULT_FAR } = view;
		if (far === Infinity) computeInfinitePerspectiveOffCenter(this, left, right, bottom, top, near);
		else frustum(this, left, right, bottom, top, near, far);
		return this.check();
	}
	/**
	* Generates a look-at matrix with the given eye position, focal point,
	* and up axis
	* @param view.eye - (vector) Position of the viewer
	* @param view.center - (vector) Point the viewer is looking at
	* @param view.up - (vector) Up axis
	* @returns self
	*/
	lookAt(view) {
		const { eye, center = [
			0,
			0,
			0
		], up = [
			0,
			1,
			0
		] } = view;
		lookAt(this, eye, center, up);
		return this.check();
	}
	/**
	* Generates a orthogonal projection matrix with the given bounds
	* from "traditional" view space parameters
	* @param view.left - Left bound of the frustum
	* @param view.right number  Right bound of the frustum
	* @param view.bottom - Bottom bound of the frustum
	* @param view.top number  Top bound of the frustum
	* @param view.near - Near bound of the frustum
	* @param view.far number  Far bound of the frustum
	* @returns self
	*/
	ortho(view) {
		const { left, right, bottom, top, near = DEFAULT_NEAR, far = DEFAULT_FAR } = view;
		ortho(this, left, right, bottom, top, near, far);
		return this.check();
	}
	/**
	* Generates an orthogonal projection matrix with the same parameters
	* as a perspective matrix (plus focalDistance)
	* @param view.fovy Vertical field of view in radians
	* @param view.aspect Aspect ratio. Typically viewport width / viewport height
	* @param view.focalDistance Distance in the view frustum used for extent calculations
	* @param view.near Near bound of the frustum
	* @param view.far Far bound of the frustum
	* @returns self
	*/
	orthographic(view) {
		const { fovy = DEFAULT_FOVY, aspect = DEFAULT_ASPECT, focalDistance = 1, near = DEFAULT_NEAR, far = DEFAULT_FAR } = view;
		checkRadians(fovy);
		const halfY = fovy / 2;
		const top = focalDistance * Math.tan(halfY);
		const right = top * aspect;
		return this.ortho({
			left: -right,
			right,
			bottom: -top,
			top,
			near,
			far
		});
	}
	/**
	* Generates a perspective projection matrix with the given bounds
	* @param view.fovy Vertical field of view in radians
	* @param view.aspect Aspect ratio. typically viewport width/height
	* @param view.near Near bound of the frustum
	* @param view.far Far bound of the frustum
	* @returns self
	*/
	perspective(view) {
		const { fovy = 45 * Math.PI / 180, aspect = 1, near = .1, far = 500 } = view;
		checkRadians(fovy);
		perspective(this, fovy, aspect, near, far);
		return this.check();
	}
	determinant() {
		return determinant(this);
	}
	/**
	* Extracts the non-uniform scale assuming the matrix is an affine transformation.
	* The scales are the "lengths" of the column vectors in the upper-left 3x3 matrix.
	* @param result
	* @returns self
	*/
	getScale(result = [
		-0,
		-0,
		-0
	]) {
		result[0] = Math.sqrt(this[0] * this[0] + this[1] * this[1] + this[2] * this[2]);
		result[1] = Math.sqrt(this[4] * this[4] + this[5] * this[5] + this[6] * this[6]);
		result[2] = Math.sqrt(this[8] * this[8] + this[9] * this[9] + this[10] * this[10]);
		return result;
	}
	/**
	* Gets the translation portion, assuming the matrix is a affine transformation matrix.
	* @param result
	* @returns self
	*/
	getTranslation(result = [
		-0,
		-0,
		-0
	]) {
		result[0] = this[12];
		result[1] = this[13];
		result[2] = this[14];
		return result;
	}
	/**
	* Gets upper left 3x3 pure rotation matrix (non-scaling), assume affine transformation matrix
	* @param result
	* @param scaleResult
	* @returns self
	*/
	getRotation(result, scaleResult) {
		result = result || [
			-0,
			-0,
			-0,
			-0,
			-0,
			-0,
			-0,
			-0,
			-0,
			-0,
			-0,
			-0,
			-0,
			-0,
			-0,
			-0
		];
		scaleResult = scaleResult || [
			-0,
			-0,
			-0
		];
		const scale = this.getScale(scaleResult);
		const inverseScale0 = 1 / scale[0];
		const inverseScale1 = 1 / scale[1];
		const inverseScale2 = 1 / scale[2];
		result[0] = this[0] * inverseScale0;
		result[1] = this[1] * inverseScale1;
		result[2] = this[2] * inverseScale2;
		result[3] = 0;
		result[4] = this[4] * inverseScale0;
		result[5] = this[5] * inverseScale1;
		result[6] = this[6] * inverseScale2;
		result[7] = 0;
		result[8] = this[8] * inverseScale0;
		result[9] = this[9] * inverseScale1;
		result[10] = this[10] * inverseScale2;
		result[11] = 0;
		result[12] = 0;
		result[13] = 0;
		result[14] = 0;
		result[15] = 1;
		return result;
	}
	/**
	*
	* @param result
	* @param scaleResult
	* @returns self
	*/
	getRotationMatrix3(result, scaleResult) {
		result = result || [
			-0,
			-0,
			-0,
			-0,
			-0,
			-0,
			-0,
			-0,
			-0
		];
		scaleResult = scaleResult || [
			-0,
			-0,
			-0
		];
		const scale = this.getScale(scaleResult);
		const inverseScale0 = 1 / scale[0];
		const inverseScale1 = 1 / scale[1];
		const inverseScale2 = 1 / scale[2];
		result[0] = this[0] * inverseScale0;
		result[1] = this[1] * inverseScale1;
		result[2] = this[2] * inverseScale2;
		result[3] = this[4] * inverseScale0;
		result[4] = this[5] * inverseScale1;
		result[5] = this[6] * inverseScale2;
		result[6] = this[8] * inverseScale0;
		result[7] = this[9] * inverseScale1;
		result[8] = this[10] * inverseScale2;
		return result;
	}
	transpose() {
		transpose(this, this);
		return this.check();
	}
	invert() {
		invert(this, this);
		return this.check();
	}
	multiplyLeft(a) {
		multiply(this, a, this);
		return this.check();
	}
	multiplyRight(a) {
		multiply(this, this, a);
		return this.check();
	}
	rotateX(radians) {
		rotateX(this, this, radians);
		return this.check();
	}
	rotateY(radians) {
		rotateY(this, this, radians);
		return this.check();
	}
	/**
	* Rotates a matrix by the given angle around the Z axis.
	* @param radians
	* @returns self
	*/
	rotateZ(radians) {
		rotateZ(this, this, radians);
		return this.check();
	}
	/**
	*
	* @param param0
	* @returns self
	*/
	rotateXYZ(angleXYZ) {
		return this.rotateX(angleXYZ[0]).rotateY(angleXYZ[1]).rotateZ(angleXYZ[2]);
	}
	/**
	*
	* @param radians
	* @param axis
	* @returns self
	*/
	rotateAxis(radians, axis) {
		rotate(this, this, radians, axis);
		return this.check();
	}
	/**
	*
	* @param factor
	* @returns self
	*/
	scale(factor) {
		scale$1(this, this, Array.isArray(factor) ? factor : [
			factor,
			factor,
			factor
		]);
		return this.check();
	}
	/**
	*
	* @param vec
	* @returns self
	*/
	translate(vector) {
		translate(this, this, vector);
		return this.check();
	}
	/**
	* Transforms any 2, 3 or 4 element vector. 2 and 3 elements are treated as points
	* @param vector
	* @param result
	* @returns self
	*/
	transform(vector, result) {
		if (vector.length === 4) {
			result = transformMat4(result || [
				-0,
				-0,
				-0,
				-0
			], vector, this);
			checkVector(result, 4);
			return result;
		}
		return this.transformAsPoint(vector, result);
	}
	/**
	* Transforms any 2 or 3 element array as point (w implicitly 1)
	* @param vector
	* @param result
	* @returns self
	*/
	transformAsPoint(vector, result) {
		const { length } = vector;
		let out;
		switch (length) {
			case 2:
				out = transformMat4$2(result || [-0, -0], vector, this);
				break;
			case 3:
				out = transformMat4$1(result || [
					-0,
					-0,
					-0
				], vector, this);
				break;
			default: throw new Error("Illegal vector");
		}
		checkVector(out, vector.length);
		return out;
	}
	/**
	* Transforms any 2 or 3 element array as vector (w implicitly 0)
	* @param vector
	* @param result
	* @returns self
	*/
	transformAsVector(vector, result) {
		let out;
		switch (vector.length) {
			case 2:
				out = vec2_transformMat4AsVector(result || [-0, -0], vector, this);
				break;
			case 3:
				out = vec3_transformMat4AsVector(result || [
					-0,
					-0,
					-0
				], vector, this);
				break;
			default: throw new Error("Illegal vector");
		}
		checkVector(out, vector.length);
		return out;
	}
	/** @deprecated */
	transformPoint(vector, result) {
		return this.transformAsPoint(vector, result);
	}
	/** @deprecated */
	transformVector(vector, result) {
		return this.transformAsPoint(vector, result);
	}
	/** @deprecated */
	transformDirection(vector, result) {
		return this.transformAsVector(vector, result);
	}
	makeRotationX(radians) {
		return this.identity().rotateX(radians);
	}
	makeTranslation(x, y, z) {
		return this.identity().translate([
			x,
			y,
			z
		]);
	}
};
var ZERO;
var IDENTITY$1;
function getZeroMatrix() {
	if (!ZERO) {
		ZERO = new Matrix4([
			0,
			0,
			0,
			0,
			0,
			0,
			0,
			0,
			0,
			0,
			0,
			0,
			0,
			0,
			0,
			0
		]);
		Object.freeze(ZERO);
	}
	return ZERO;
}
function getIdentityMatrix() {
	if (!IDENTITY$1) {
		IDENTITY$1 = new Matrix4();
		Object.freeze(IDENTITY$1);
	}
	return IDENTITY$1;
}
function checkRadians(possiblyDegrees) {
	if (possiblyDegrees > Math.PI * 2) throw Error("expected radians");
}
function computeInfinitePerspectiveOffCenter(result, left, right, bottom, top, near) {
	const column0Row0 = 2 * near / (right - left);
	const column1Row1 = 2 * near / (top - bottom);
	const column2Row0 = (right + left) / (right - left);
	const column2Row1 = (top + bottom) / (top - bottom);
	const column2Row2 = -1;
	const column2Row3 = -1;
	const column3Row2 = -2 * near;
	result[0] = column0Row0;
	result[1] = 0;
	result[2] = 0;
	result[3] = 0;
	result[4] = 0;
	result[5] = column1Row1;
	result[6] = 0;
	result[7] = 0;
	result[8] = column2Row0;
	result[9] = column2Row1;
	result[10] = column2Row2;
	result[11] = column2Row3;
	result[12] = 0;
	result[13] = 0;
	result[14] = column3Row2;
	result[15] = 0;
	return result;
}
//#endregion
//#region node_modules/@luma.gl/shadertools/dist/lib/color/normalize-byte-colors.js
/**
* Resolves whether semantic colors should be interpreted as byte-style `0..255` values.
* @param useByteColors - Explicit color interpretation flag.
* @param defaultUseByteColors - Fallback value when `useByteColors` is omitted.
* @returns `true` when semantic colors should be normalized from bytes, otherwise `false`.
*/
function resolveUseByteColors(useByteColors, defaultUseByteColors = true) {
	return useByteColors ?? defaultUseByteColors;
}
/**
* Normalizes an RGB semantic color to float space when byte-style colors are enabled.
* @param color - Input RGB semantic color.
* @param useByteColors - When `true`, divide components by `255`.
* @returns The normalized RGB color.
*/
function normalizeByteColor3(color = [
	0,
	0,
	0
], useByteColors = true) {
	if (!useByteColors) return [...color];
	return color.map((component) => component / 255);
}
/**
* Normalizes an RGBA semantic color to float space when byte-style colors are enabled.
* @param color - Input RGB or RGBA semantic color.
* @param useByteColors - When `true`, divide components by `255`.
* @returns The normalized RGBA color, adding an opaque alpha channel when needed.
*/
function normalizeByteColor4(color, useByteColors = true) {
	const normalizedColor = normalizeByteColor3(color.slice(0, 3), useByteColors);
	const hasAlpha = Number.isFinite(color[3]);
	const alpha = hasAlpha ? color[3] : 1;
	return [
		normalizedColor[0],
		normalizedColor[1],
		normalizedColor[2],
		useByteColors && hasAlpha ? alpha / 255 : alpha
	];
}
/**
* 32 bit math library (fixups for GPUs)
*/
var fp32 = {
	name: "fp32",
	vs: `\
#ifdef LUMA_FP32_TAN_PRECISION_WORKAROUND

// All these functions are for substituting tan() function from Intel GPU only
const float TWO_PI = 6.2831854820251465;
const float PI_2 = 1.5707963705062866;
const float PI_16 = 0.1963495463132858;

const float SIN_TABLE_0 = 0.19509032368659973;
const float SIN_TABLE_1 = 0.3826834261417389;
const float SIN_TABLE_2 = 0.5555702447891235;
const float SIN_TABLE_3 = 0.7071067690849304;

const float COS_TABLE_0 = 0.9807852506637573;
const float COS_TABLE_1 = 0.9238795042037964;
const float COS_TABLE_2 = 0.8314695954322815;
const float COS_TABLE_3 = 0.7071067690849304;

const float INVERSE_FACTORIAL_3 = 1.666666716337204e-01; // 1/3!
const float INVERSE_FACTORIAL_5 = 8.333333767950535e-03; // 1/5!
const float INVERSE_FACTORIAL_7 = 1.9841270113829523e-04; // 1/7!
const float INVERSE_FACTORIAL_9 = 2.75573188446287533e-06; // 1/9!

float sin_taylor_fp32(float a) {
  float r, s, t, x;

  if (a == 0.0) {
    return 0.0;
  }

  x = -a * a;
  s = a;
  r = a;

  r = r * x;
  t = r * INVERSE_FACTORIAL_3;
  s = s + t;

  r = r * x;
  t = r * INVERSE_FACTORIAL_5;
  s = s + t;

  r = r * x;
  t = r * INVERSE_FACTORIAL_7;
  s = s + t;

  r = r * x;
  t = r * INVERSE_FACTORIAL_9;
  s = s + t;

  return s;
}

void sincos_taylor_fp32(float a, out float sin_t, out float cos_t) {
  if (a == 0.0) {
    sin_t = 0.0;
    cos_t = 1.0;
  }
  sin_t = sin_taylor_fp32(a);
  cos_t = sqrt(1.0 - sin_t * sin_t);
}

float tan_taylor_fp32(float a) {
    float sin_a;
    float cos_a;

    if (a == 0.0) {
        return 0.0;
    }

    // 2pi range reduction
    float z = floor(a / TWO_PI);
    float r = a - TWO_PI * z;

    float t;
    float q = floor(r / PI_2 + 0.5);
    int j = int(q);

    if (j < -2 || j > 2) {
        return 1.0 / 0.0;
    }

    t = r - PI_2 * q;

    q = floor(t / PI_16 + 0.5);
    int k = int(q);
    int abs_k = int(abs(float(k)));

    if (abs_k > 4) {
        return 1.0 / 0.0;
    } else {
        t = t - PI_16 * q;
    }

    float u = 0.0;
    float v = 0.0;

    float sin_t, cos_t;
    float s, c;
    sincos_taylor_fp32(t, sin_t, cos_t);

    if (k == 0) {
        s = sin_t;
        c = cos_t;
    } else {
        if (abs(float(abs_k) - 1.0) < 0.5) {
            u = COS_TABLE_0;
            v = SIN_TABLE_0;
        } else if (abs(float(abs_k) - 2.0) < 0.5) {
            u = COS_TABLE_1;
            v = SIN_TABLE_1;
        } else if (abs(float(abs_k) - 3.0) < 0.5) {
            u = COS_TABLE_2;
            v = SIN_TABLE_2;
        } else if (abs(float(abs_k) - 4.0) < 0.5) {
            u = COS_TABLE_3;
            v = SIN_TABLE_3;
        }
        if (k > 0) {
            s = u * sin_t + v * cos_t;
            c = u * cos_t - v * sin_t;
        } else {
            s = u * sin_t - v * cos_t;
            c = u * cos_t + v * sin_t;
        }
    }

    if (j == 0) {
        sin_a = s;
        cos_a = c;
    } else if (j == 1) {
        sin_a = c;
        cos_a = -s;
    } else if (j == -1) {
        sin_a = -c;
        cos_a = s;
    } else {
        sin_a = -s;
        cos_a = -c;
    }
    return sin_a / cos_a;
}
#endif

float tan_fp32(float a) {
#ifdef LUMA_FP32_TAN_PRECISION_WORKAROUND
  return tan_taylor_fp32(a);
#else
  return tan(a);
#endif
}
`
};
/**
* Deprecated legacy picking module retained for compatibility with existing
* shadertools users such as deck.gl. Keep the shader contract stable.
*
* Provides support for color-coding-based picking and highlighting.
* In particular, supports picking a specific instance in an instanced
* draw call and highlighting an instance based on its picking color,
* and correspondingly, supports picking and highlighting groups of
* primitives with the same picking color in non-instanced draw-calls
*/
var picking = {
	props: {},
	uniforms: {},
	name: "picking",
	uniformTypes: {
		isActive: "f32",
		isAttribute: "f32",
		isHighlightActive: "f32",
		useByteColors: "f32",
		highlightedObjectColor: "vec3<f32>",
		highlightColor: "vec4<f32>"
	},
	defaultUniforms: {
		isActive: false,
		isAttribute: false,
		isHighlightActive: false,
		useByteColors: true,
		highlightedObjectColor: [
			0,
			0,
			0
		],
		highlightColor: [
			0,
			1,
			1,
			1
		]
	},
	vs: `\
layout(std140) uniform pickingUniforms {
  float isActive;
  float isAttribute;
  float isHighlightActive;
  float useByteColors;
  vec3 highlightedObjectColor;
  vec4 highlightColor;
} picking;

out vec4 picking_vRGBcolor_Avalid;

// Normalize unsigned byte color to 0-1 range
vec3 picking_normalizeColor(vec3 color) {
  return picking.useByteColors > 0.5 ? color / 255.0 : color;
}

// Normalize unsigned byte color to 0-1 range
vec4 picking_normalizeColor(vec4 color) {
  return picking.useByteColors > 0.5 ? color / 255.0 : color;
}

bool picking_isColorZero(vec3 color) {
  return dot(color, vec3(1.0)) < 0.00001;
}

bool picking_isColorValid(vec3 color) {
  return dot(color, vec3(1.0)) > 0.00001;
}

// Check if this vertex is highlighted 
bool isVertexHighlighted(vec3 vertexColor) {
  vec3 highlightedObjectColor = picking_normalizeColor(picking.highlightedObjectColor);
  return
    bool(picking.isHighlightActive) && picking_isColorZero(abs(vertexColor - highlightedObjectColor));
}

// Set the current picking color
void picking_setPickingColor(vec3 pickingColor) {
  pickingColor = picking_normalizeColor(pickingColor);

  if (bool(picking.isActive)) {
    // Use alpha as the validity flag. If pickingColor is [0, 0, 0] fragment is non-pickable
    picking_vRGBcolor_Avalid.a = float(picking_isColorValid(pickingColor));

    if (!bool(picking.isAttribute)) {
      // Stores the picking color so that the fragment shader can render it during picking
      picking_vRGBcolor_Avalid.rgb = pickingColor;
    }
  } else {
    // Do the comparison with selected item color in vertex shader as it should mean fewer compares
    picking_vRGBcolor_Avalid.a = float(isVertexHighlighted(pickingColor));
  }
}

void picking_setPickingAttribute(float value) {
  if (bool(picking.isAttribute)) {
    picking_vRGBcolor_Avalid.r = value;
  }
}

void picking_setPickingAttribute(vec2 value) {
  if (bool(picking.isAttribute)) {
    picking_vRGBcolor_Avalid.rg = value;
  }
}

void picking_setPickingAttribute(vec3 value) {
  if (bool(picking.isAttribute)) {
    picking_vRGBcolor_Avalid.rgb = value;
  }
}
`,
	fs: `\
layout(std140) uniform pickingUniforms {
  float isActive;
  float isAttribute;
  float isHighlightActive;
  float useByteColors;
  vec3 highlightedObjectColor;
  vec4 highlightColor;
} picking;

in vec4 picking_vRGBcolor_Avalid;

/*
 * Returns highlight color if this item is selected.
 */
vec4 picking_filterHighlightColor(vec4 color) {
  // If we are still picking, we don't highlight
  if (picking.isActive > 0.5) {
    return color;
  }

  bool selected = bool(picking_vRGBcolor_Avalid.a);

  if (selected) {
    // Blend in highlight color based on its alpha value
    float highLightAlpha = picking.highlightColor.a;
    float blendedAlpha = highLightAlpha + color.a * (1.0 - highLightAlpha);
    float highLightRatio = highLightAlpha / blendedAlpha;

    vec3 blendedRGB = mix(color.rgb, picking.highlightColor.rgb, highLightRatio);
    return vec4(blendedRGB, blendedAlpha);
  } else {
    return color;
  }
}

/*
 * Returns picking color if picking enabled else unmodified argument.
 */
vec4 picking_filterPickingColor(vec4 color) {
  if (bool(picking.isActive)) {
    if (picking_vRGBcolor_Avalid.a == 0.0) {
      discard;
    }
    return picking_vRGBcolor_Avalid;
  }
  return color;
}

/*
 * Returns picking color if picking is enabled if not
 * highlight color if this item is selected, otherwise unmodified argument.
 */
vec4 picking_filterColor(vec4 color) {
  vec4 highlightColor = picking_filterHighlightColor(color);
  return picking_filterPickingColor(highlightColor);
}
`,
	getUniforms: getUniforms$1
};
function getUniforms$1(opts = {}, prevUniforms) {
	const uniforms = {};
	const useByteColors = resolveUseByteColors(opts.useByteColors, true);
	if (opts.highlightedObjectColor === void 0) {} else if (opts.highlightedObjectColor === null) uniforms.isHighlightActive = false;
	else {
		uniforms.isHighlightActive = true;
		uniforms.highlightedObjectColor = opts.highlightedObjectColor.slice(0, 3);
	}
	if (opts.highlightColor) uniforms.highlightColor = normalizeByteColor4(opts.highlightColor, useByteColors);
	if (opts.isActive !== void 0) {
		uniforms.isActive = Boolean(opts.isActive);
		uniforms.isAttribute = Boolean(opts.isAttribute);
	}
	if (opts.useByteColors !== void 0) uniforms.useByteColors = Boolean(opts.useByteColors);
	return uniforms;
}
//#endregion
//#region node_modules/@luma.gl/core/dist/utils/stats-manager.js
var GPU_TIME_AND_MEMORY_STATS$1 = "GPU Time and Memory";
var GPU_TIME_AND_MEMORY_STAT_ORDER = [
	"Adapter",
	"GPU",
	"GPU Type",
	"GPU Backend",
	"Frame Rate",
	"CPU Time",
	"GPU Time",
	"GPU Memory",
	"Buffer Memory",
	"Texture Memory",
	"Referenced Buffer Memory",
	"Referenced Texture Memory",
	"Swap Chain Texture"
];
var ORDERED_STATS_CACHE$1 = /* @__PURE__ */ new WeakMap();
var ORDERED_STAT_NAME_SET_CACHE$1 = /* @__PURE__ */ new WeakMap();
/**
* Helper class managing a collection of probe.gl stats objects
*/
var StatsManager = class {
	stats = /* @__PURE__ */ new Map();
	getStats(name) {
		return this.get(name);
	}
	get(name) {
		if (!this.stats.has(name)) this.stats.set(name, new Stats({ id: name }));
		const stats = this.stats.get(name);
		if (name === GPU_TIME_AND_MEMORY_STATS$1) initializeStats$1(stats, GPU_TIME_AND_MEMORY_STAT_ORDER);
		return stats;
	}
};
/** Global stats for all luma.gl devices */
var lumaStats = new StatsManager();
function initializeStats$1(stats, orderedStatNames) {
	const statsMap = stats.stats;
	let addedOrderedStat = false;
	for (const statName of orderedStatNames) if (!statsMap[statName]) {
		stats.get(statName);
		addedOrderedStat = true;
	}
	const statCount = Object.keys(statsMap).length;
	const cachedStats = ORDERED_STATS_CACHE$1.get(stats);
	if (!addedOrderedStat && cachedStats?.orderedStatNames === orderedStatNames && cachedStats.statCount === statCount) return;
	const reorderedStats = {};
	let orderedStatNamesSet = ORDERED_STAT_NAME_SET_CACHE$1.get(orderedStatNames);
	if (!orderedStatNamesSet) {
		orderedStatNamesSet = new Set(orderedStatNames);
		ORDERED_STAT_NAME_SET_CACHE$1.set(orderedStatNames, orderedStatNamesSet);
	}
	for (const statName of orderedStatNames) if (statsMap[statName]) reorderedStats[statName] = statsMap[statName];
	for (const [statName, stat] of Object.entries(statsMap)) if (!orderedStatNamesSet.has(statName)) reorderedStats[statName] = stat;
	for (const statName of Object.keys(statsMap)) delete statsMap[statName];
	Object.assign(statsMap, reorderedStats);
	ORDERED_STATS_CACHE$1.set(stats, {
		orderedStatNames,
		statCount
	});
}
//#endregion
//#region node_modules/@luma.gl/core/dist/utils/log.js
/** Global log instance */
var log = new ProbeLog({ id: "luma.gl" });
//#endregion
//#region node_modules/@luma.gl/core/dist/utils/uid.js
var uidCounters = {};
/**
* Returns a UID.
* @param id= - Identifier base name
* @return uid
**/
function uid(id = "id") {
	uidCounters[id] = uidCounters[id] || 1;
	return `${id}-${uidCounters[id]++}`;
}
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/resources/resource.js
var CPU_HOTSPOT_PROFILER_MODULE = "cpu-hotspot-profiler";
var RESOURCE_COUNTS_STATS = "GPU Resource Counts";
var LEGACY_RESOURCE_COUNTS_STATS = "Resource Counts";
var GPU_TIME_AND_MEMORY_STATS = "GPU Time and Memory";
var BASE_RESOURCE_COUNT_ORDER = [
	"Resources",
	"Buffers",
	"Textures",
	"Samplers",
	"TextureViews",
	"Framebuffers",
	"QuerySets",
	"Shaders",
	"RenderPipelines",
	"ComputePipelines",
	"PipelineLayouts",
	"VertexArrays",
	"RenderPasss",
	"ComputePasss",
	"CommandEncoders",
	"CommandBuffers"
];
var WEBGL_RESOURCE_COUNT_ORDER = [
	"Resources",
	"Buffers",
	"Textures",
	"Samplers",
	"TextureViews",
	"Framebuffers",
	"QuerySets",
	"Shaders",
	"RenderPipelines",
	"SharedRenderPipelines",
	"ComputePipelines",
	"PipelineLayouts",
	"VertexArrays",
	"RenderPasss",
	"ComputePasss",
	"CommandEncoders",
	"CommandBuffers"
];
var BASE_RESOURCE_COUNT_STAT_ORDER = BASE_RESOURCE_COUNT_ORDER.flatMap((resourceType) => [`${resourceType} Created`, `${resourceType} Active`]);
var WEBGL_RESOURCE_COUNT_STAT_ORDER = WEBGL_RESOURCE_COUNT_ORDER.flatMap((resourceType) => [`${resourceType} Created`, `${resourceType} Active`]);
var ORDERED_STATS_CACHE = /* @__PURE__ */ new WeakMap();
var ORDERED_STAT_NAME_SET_CACHE = /* @__PURE__ */ new WeakMap();
/**
* Base class for GPU (WebGPU/WebGL) Resources
*/
var Resource = class {
	/** Default properties for resource */
	static defaultProps = {
		id: "undefined",
		handle: void 0,
		userData: void 0
	};
	toString() {
		return `${this[Symbol.toStringTag] || this.constructor.name}:"${this.id}"`;
	}
	/** props.id, for debugging. */
	id;
	/** The props that this resource was created with */
	props;
	/** User data object, reserved for the application */
	userData = {};
	/** The device that this resource is associated with - TODO can we remove this dup? */
	_device;
	/** Whether this resource has been destroyed */
	destroyed = false;
	/** For resources that allocate GPU memory */
	allocatedBytes = 0;
	/** Stats bucket currently holding the tracked allocation */
	allocatedBytesName = null;
	/** Attached resources will be destroyed when this resource is destroyed. Tracks auto-created "sub" resources. */
	_attachedResources = /* @__PURE__ */ new Set();
	/**
	* Create a new Resource. Called from Subclass
	*/
	constructor(device, props, defaultProps) {
		if (!device) throw new Error("no device");
		this._device = device;
		this.props = selectivelyMerge(props, defaultProps);
		const id = this.props.id !== "undefined" ? this.props.id : uid(this[Symbol.toStringTag]);
		this.props.id = id;
		this.id = id;
		this.userData = this.props.userData || {};
		this.addStats();
	}
	/**
	* destroy can be called on any resource to release it before it is garbage collected.
	*/
	destroy() {
		if (this.destroyed) return;
		this.destroyResource();
	}
	/** @deprecated Use destroy() */
	delete() {
		this.destroy();
		return this;
	}
	/**
	* Combines a map of user props and default props, only including props from defaultProps
	* @returns returns a map of overridden default props
	*/
	getProps() {
		return this.props;
	}
	/**
	* Attaches a resource. Attached resources are auto destroyed when this resource is destroyed
	* Called automatically when sub resources are auto created but can be called by application
	*/
	attachResource(resource) {
		this._attachedResources.add(resource);
	}
	/**
	* Detach an attached resource. The resource will no longer be auto-destroyed when this resource is destroyed.
	*/
	detachResource(resource) {
		this._attachedResources.delete(resource);
	}
	/**
	* Destroys a resource (only if owned), and removes from the owned (auto-destroy) list for this resource.
	*/
	destroyAttachedResource(resource) {
		if (this._attachedResources.delete(resource)) resource.destroy();
	}
	/** Destroy all owned resources. Make sure the resources are no longer needed before calling. */
	destroyAttachedResources() {
		for (const resource of this._attachedResources) resource.destroy();
		this._attachedResources = /* @__PURE__ */ new Set();
	}
	/** Perform all destroy steps. Can be called by derived resources when overriding destroy() */
	destroyResource() {
		if (this.destroyed) return;
		this.destroyAttachedResources();
		this.removeStats();
		this.destroyed = true;
	}
	/** Called by .destroy() to track object destruction. Subclass must call if overriding destroy() */
	removeStats() {
		const profiler = getCpuHotspotProfiler(this._device);
		const startTime = profiler ? getTimestamp() : 0;
		const statsObjects = [this._device.statsManager.getStats(RESOURCE_COUNTS_STATS), this._device.statsManager.getStats(LEGACY_RESOURCE_COUNTS_STATS)];
		const orderedStatNames = getResourceCountStatOrder(this._device);
		for (const stats of statsObjects) initializeStats(stats, orderedStatNames);
		const name = this.getStatsName();
		for (const stats of statsObjects) {
			stats.get("Resources Active").decrementCount();
			stats.get(`${name}s Active`).decrementCount();
		}
		if (profiler) {
			profiler.statsBookkeepingCalls = (profiler.statsBookkeepingCalls || 0) + 1;
			profiler.statsBookkeepingTimeMs = (profiler.statsBookkeepingTimeMs || 0) + (getTimestamp() - startTime);
		}
	}
	/** Called by subclass to track memory allocations */
	trackAllocatedMemory(bytes, name = this.getStatsName()) {
		const profiler = getCpuHotspotProfiler(this._device);
		const startTime = profiler ? getTimestamp() : 0;
		const stats = this._device.statsManager.getStats(GPU_TIME_AND_MEMORY_STATS);
		if (this.allocatedBytes > 0 && this.allocatedBytesName) {
			stats.get("GPU Memory").subtractCount(this.allocatedBytes);
			stats.get(`${this.allocatedBytesName} Memory`).subtractCount(this.allocatedBytes);
		}
		stats.get("GPU Memory").addCount(bytes);
		stats.get(`${name} Memory`).addCount(bytes);
		if (profiler) {
			profiler.statsBookkeepingCalls = (profiler.statsBookkeepingCalls || 0) + 1;
			profiler.statsBookkeepingTimeMs = (profiler.statsBookkeepingTimeMs || 0) + (getTimestamp() - startTime);
		}
		this.allocatedBytes = bytes;
		this.allocatedBytesName = name;
	}
	/** Called by subclass to track handle-backed memory allocations separately from owned allocations */
	trackReferencedMemory(bytes, name = this.getStatsName()) {
		this.trackAllocatedMemory(bytes, `Referenced ${name}`);
	}
	/** Called by subclass to track memory deallocations */
	trackDeallocatedMemory(name = this.getStatsName()) {
		if (this.allocatedBytes === 0) {
			this.allocatedBytesName = null;
			return;
		}
		const profiler = getCpuHotspotProfiler(this._device);
		const startTime = profiler ? getTimestamp() : 0;
		const stats = this._device.statsManager.getStats(GPU_TIME_AND_MEMORY_STATS);
		stats.get("GPU Memory").subtractCount(this.allocatedBytes);
		stats.get(`${this.allocatedBytesName || name} Memory`).subtractCount(this.allocatedBytes);
		if (profiler) {
			profiler.statsBookkeepingCalls = (profiler.statsBookkeepingCalls || 0) + 1;
			profiler.statsBookkeepingTimeMs = (profiler.statsBookkeepingTimeMs || 0) + (getTimestamp() - startTime);
		}
		this.allocatedBytes = 0;
		this.allocatedBytesName = null;
	}
	/** Called by subclass to deallocate handle-backed memory tracked via trackReferencedMemory() */
	trackDeallocatedReferencedMemory(name = this.getStatsName()) {
		this.trackDeallocatedMemory(`Referenced ${name}`);
	}
	/** Called by resource constructor to track object creation */
	addStats() {
		const name = this.getStatsName();
		const profiler = getCpuHotspotProfiler(this._device);
		const startTime = profiler ? getTimestamp() : 0;
		const statsObjects = [this._device.statsManager.getStats(RESOURCE_COUNTS_STATS), this._device.statsManager.getStats(LEGACY_RESOURCE_COUNTS_STATS)];
		const orderedStatNames = getResourceCountStatOrder(this._device);
		for (const stats of statsObjects) initializeStats(stats, orderedStatNames);
		for (const stats of statsObjects) {
			stats.get("Resources Created").incrementCount();
			stats.get("Resources Active").incrementCount();
			stats.get(`${name}s Created`).incrementCount();
			stats.get(`${name}s Active`).incrementCount();
		}
		if (profiler) {
			profiler.statsBookkeepingCalls = (profiler.statsBookkeepingCalls || 0) + 1;
			profiler.statsBookkeepingTimeMs = (profiler.statsBookkeepingTimeMs || 0) + (getTimestamp() - startTime);
		}
		recordTransientCanvasResourceCreate(this._device, name);
	}
	/** Canonical resource name used for stats buckets. */
	getStatsName() {
		return getCanonicalResourceName(this);
	}
};
/**
* Combines a map of user props and default props, only including props from defaultProps
* @param props
* @param defaultProps
* @returns returns a map of overridden default props
*/
function selectivelyMerge(props, defaultProps) {
	const mergedProps = { ...defaultProps };
	for (const key in props) if (props[key] !== void 0) mergedProps[key] = props[key];
	return mergedProps;
}
function initializeStats(stats, orderedStatNames) {
	const statsMap = stats.stats;
	let addedOrderedStat = false;
	for (const statName of orderedStatNames) if (!statsMap[statName]) {
		stats.get(statName);
		addedOrderedStat = true;
	}
	const statCount = Object.keys(statsMap).length;
	const cachedStats = ORDERED_STATS_CACHE.get(stats);
	if (!addedOrderedStat && cachedStats?.orderedStatNames === orderedStatNames && cachedStats.statCount === statCount) return;
	const reorderedStats = {};
	let orderedStatNamesSet = ORDERED_STAT_NAME_SET_CACHE.get(orderedStatNames);
	if (!orderedStatNamesSet) {
		orderedStatNamesSet = new Set(orderedStatNames);
		ORDERED_STAT_NAME_SET_CACHE.set(orderedStatNames, orderedStatNamesSet);
	}
	for (const statName of orderedStatNames) if (statsMap[statName]) reorderedStats[statName] = statsMap[statName];
	for (const [statName, stat] of Object.entries(statsMap)) if (!orderedStatNamesSet.has(statName)) reorderedStats[statName] = stat;
	for (const statName of Object.keys(statsMap)) delete statsMap[statName];
	Object.assign(statsMap, reorderedStats);
	ORDERED_STATS_CACHE.set(stats, {
		orderedStatNames,
		statCount
	});
}
function getResourceCountStatOrder(device) {
	return device.type === "webgl" ? WEBGL_RESOURCE_COUNT_STAT_ORDER : BASE_RESOURCE_COUNT_STAT_ORDER;
}
function getCpuHotspotProfiler(device) {
	const profiler = device.userData[CPU_HOTSPOT_PROFILER_MODULE];
	return profiler?.enabled ? profiler : null;
}
function getTimestamp() {
	return globalThis.performance?.now?.() ?? Date.now();
}
function recordTransientCanvasResourceCreate(device, name) {
	const profiler = getCpuHotspotProfiler(device);
	if (!profiler || !profiler.activeDefaultFramebufferAcquireDepth) return;
	profiler.transientCanvasResourceCreates = (profiler.transientCanvasResourceCreates || 0) + 1;
	switch (name) {
		case "Texture":
			profiler.transientCanvasTextureCreates = (profiler.transientCanvasTextureCreates || 0) + 1;
			break;
		case "TextureView":
			profiler.transientCanvasTextureViewCreates = (profiler.transientCanvasTextureViewCreates || 0) + 1;
			break;
		case "Sampler":
			profiler.transientCanvasSamplerCreates = (profiler.transientCanvasSamplerCreates || 0) + 1;
			break;
		case "Framebuffer":
			profiler.transientCanvasFramebufferCreates = (profiler.transientCanvasFramebufferCreates || 0) + 1;
			break;
		default: break;
	}
}
function getCanonicalResourceName(resource) {
	let prototype = Object.getPrototypeOf(resource);
	while (prototype) {
		const parentPrototype = Object.getPrototypeOf(prototype);
		if (!parentPrototype || parentPrototype === Resource.prototype) return getPrototypeToStringTag(prototype) || resource[Symbol.toStringTag] || resource.constructor.name;
		prototype = parentPrototype;
	}
	return resource[Symbol.toStringTag] || resource.constructor.name;
}
function getPrototypeToStringTag(prototype) {
	const descriptor = Object.getOwnPropertyDescriptor(prototype, Symbol.toStringTag);
	if (typeof descriptor?.get === "function") return descriptor.get.call(prototype);
	if (typeof descriptor?.value === "string") return descriptor.value;
	return null;
}
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/resources/buffer.js
/** Abstract GPU buffer */
var Buffer = class Buffer extends Resource {
	/** Index buffer */
	static INDEX = 16;
	/** Vertex buffer */
	static VERTEX = 32;
	/** Uniform buffer */
	static UNIFORM = 64;
	/** Storage buffer */
	static STORAGE = 128;
	static INDIRECT = 256;
	static QUERY_RESOLVE = 512;
	static MAP_READ = 1;
	static MAP_WRITE = 2;
	static COPY_SRC = 4;
	static COPY_DST = 8;
	get [Symbol.toStringTag]() {
		return "Buffer";
	}
	/** The usage with which this buffer was created */
	usage;
	/** For index buffers, whether indices are 8, 16 or 32 bit. Note: uint8 indices are automatically converted to uint16 for WebGPU compatibility */
	indexType;
	/** "Time" of last update, can be used to check if redraw is needed */
	updateTimestamp;
	constructor(device, props) {
		const deducedProps = { ...props };
		if ((props.usage || 0) & Buffer.INDEX && !props.indexType) {
			if (props.data instanceof Uint32Array) deducedProps.indexType = "uint32";
			else if (props.data instanceof Uint16Array) deducedProps.indexType = "uint16";
			else if (props.data instanceof Uint8Array) deducedProps.indexType = "uint8";
		}
		delete deducedProps.data;
		super(device, deducedProps, Buffer.defaultProps);
		this.usage = deducedProps.usage || 0;
		this.indexType = deducedProps.indexType;
		this.updateTimestamp = device.incrementTimestamp();
	}
	/**
	* Create a copy of this Buffer with new byteLength, with same props but of the specified size.
	* @note Does not copy contents of the cloned Buffer.
	*/
	clone(props) {
		return this.device.createBuffer({
			...this.props,
			...props
		});
	}
	/** Max amount of debug data saved. Two vec4's */
	static DEBUG_DATA_MAX_LENGTH = 32;
	/** A partial CPU-side copy of the data in this buffer, for debugging purposes */
	debugData = /* @__PURE__ */ new ArrayBuffer(0);
	/** This doesn't handle partial non-zero offset updates correctly */
	_setDebugData(data, _byteOffset, byteLength) {
		let arrayBufferView = null;
		let arrayBuffer;
		if (ArrayBuffer.isView(data)) {
			arrayBufferView = data;
			arrayBuffer = data.buffer;
		} else arrayBuffer = data;
		const debugDataLength = Math.min(data ? data.byteLength : byteLength, Buffer.DEBUG_DATA_MAX_LENGTH);
		if (arrayBuffer === null) this.debugData = new ArrayBuffer(debugDataLength);
		else {
			const sourceByteOffset = Math.min(arrayBufferView?.byteOffset || 0, arrayBuffer.byteLength);
			const availableByteLength = Math.max(0, arrayBuffer.byteLength - sourceByteOffset);
			const copyByteLength = Math.min(debugDataLength, availableByteLength);
			this.debugData = new Uint8Array(arrayBuffer, sourceByteOffset, copyByteLength).slice().buffer;
		}
	}
	static defaultProps = {
		...Resource.defaultProps,
		usage: 0,
		byteLength: 0,
		byteOffset: 0,
		data: null,
		indexType: "uint16",
		onMapped: void 0
	};
};
//#endregion
//#region node_modules/@luma.gl/core/dist/shadertypes/data-types/data-type-decoder.js
var DataTypeDecoder = class {
	/**
	* Gets info about a data type constant (signed or normalized)
	* @returns underlying primitive / signed types, byte length, normalization, integer, signed flags
	*/
	getDataTypeInfo(type) {
		const [signedType, primitiveType, byteLength] = NORMALIZED_TYPE_MAP[type];
		const normalized = type.includes("norm");
		return {
			signedType,
			primitiveType,
			byteLength,
			normalized,
			integer: !normalized && !type.startsWith("float"),
			signed: type.startsWith("s")
		};
	}
	/** Build a vertex format from a signed data type and a component */
	getNormalizedDataType(signedDataType) {
		const dataType = signedDataType;
		switch (dataType) {
			case "uint8": return "unorm8";
			case "sint8": return "snorm8";
			case "uint16": return "unorm16";
			case "sint16": return "snorm16";
			default: return dataType;
		}
	}
	/** Align offset to 1, 2 or 4 elements (4, 8 or 16 bytes) */
	alignTo(size, count) {
		switch (count) {
			case 1: return size;
			case 2: return size + size % 2;
			default: return size + (4 - size % 4) % 4;
		}
	}
	/** Returns the VariableShaderType that corresponds to a typed array */
	getDataType(arrayOrType) {
		const Constructor = ArrayBuffer.isView(arrayOrType) ? arrayOrType.constructor : arrayOrType;
		if (Constructor === Uint8ClampedArray) return "uint8";
		const info = Object.values(NORMALIZED_TYPE_MAP).find((entry) => Constructor === entry[4]);
		if (!info) throw new Error(Constructor.name);
		return info[0];
	}
	/** Returns the TypedArray that corresponds to a shader data type */
	getTypedArrayConstructor(type) {
		const [, , , , Constructor] = NORMALIZED_TYPE_MAP[type];
		return Constructor;
	}
};
/** Entry point for decoding luma.gl data types */
var dataTypeDecoder = new DataTypeDecoder();
var NORMALIZED_TYPE_MAP = {
	uint8: [
		"uint8",
		"u32",
		1,
		false,
		Uint8Array
	],
	sint8: [
		"sint8",
		"i32",
		1,
		false,
		Int8Array
	],
	unorm8: [
		"uint8",
		"f32",
		1,
		true,
		Uint8Array
	],
	snorm8: [
		"sint8",
		"f32",
		1,
		true,
		Int8Array
	],
	uint16: [
		"uint16",
		"u32",
		2,
		false,
		Uint16Array
	],
	sint16: [
		"sint16",
		"i32",
		2,
		false,
		Int16Array
	],
	unorm16: [
		"uint16",
		"u32",
		2,
		true,
		Uint16Array
	],
	snorm16: [
		"sint16",
		"i32",
		2,
		true,
		Int16Array
	],
	float16: [
		"float16",
		"f16",
		2,
		false,
		Uint16Array
	],
	float32: [
		"float32",
		"f32",
		4,
		false,
		Float32Array
	],
	uint32: [
		"uint32",
		"u32",
		4,
		false,
		Uint32Array
	],
	sint32: [
		"sint32",
		"i32",
		4,
		false,
		Int32Array
	]
};
//#endregion
//#region node_modules/@luma.gl/core/dist/shadertypes/vertex-types/vertex-format-decoder.js
var VertexFormatDecoder = class {
	/**
	* Decodes a vertex format, returning type, components, byte  length and flags (integer, signed, normalized)
	*/
	getVertexFormatInfo(format) {
		let webglOnly;
		if (format.endsWith("-webgl")) {
			format.replace("-webgl", "");
			webglOnly = true;
		}
		const [type_, count] = format.split("x");
		const type = type_;
		const components = count ? parseInt(count) : 1;
		const decodedType = dataTypeDecoder.getDataTypeInfo(type);
		const result = {
			type,
			components,
			byteLength: decodedType.byteLength * components,
			integer: decodedType.integer,
			signed: decodedType.signed,
			normalized: decodedType.normalized
		};
		if (webglOnly) result.webglOnly = true;
		return result;
	}
	/** Build a vertex format from a signed data type and a component */
	makeVertexFormat(signedDataType, components, normalized) {
		const dataType = normalized ? dataTypeDecoder.getNormalizedDataType(signedDataType) : signedDataType;
		switch (dataType) {
			case "unorm8":
				if (components === 1) return "unorm8";
				if (components === 3) return "unorm8x3-webgl";
				return `${dataType}x${components}`;
			case "snorm8":
				if (components === 1) return "snorm8";
				if (components === 3) return "snorm8x3-webgl";
				return `${dataType}x${components}`;
			case "uint8":
			case "sint8":
				if (components === 1 || components === 3) throw new Error(`size: ${components}`);
				return `${dataType}x${components}`;
			case "uint16":
				if (components === 1) return "uint16";
				if (components === 3) return "uint16x3-webgl";
				return `${dataType}x${components}`;
			case "sint16":
				if (components === 1) return "sint16";
				if (components === 3) return "sint16x3-webgl";
				return `${dataType}x${components}`;
			case "unorm16":
				if (components === 1) return "unorm16";
				if (components === 3) return "unorm16x3-webgl";
				return `${dataType}x${components}`;
			case "snorm16":
				if (components === 1) return "snorm16";
				if (components === 3) return "snorm16x3-webgl";
				return `${dataType}x${components}`;
			case "float16":
				if (components === 1 || components === 3) throw new Error(`size: ${components}`);
				return `${dataType}x${components}`;
			default: return components === 1 ? dataType : `${dataType}x${components}`;
		}
	}
	/** Get the vertex format for an attribute with TypedArray and size */
	getVertexFormatFromAttribute(typedArray, size, normalized) {
		if (!size || size > 4) throw new Error(`size ${size}`);
		const components = size;
		const signedDataType = dataTypeDecoder.getDataType(typedArray);
		return this.makeVertexFormat(signedDataType, components, normalized);
	}
	/**
	* Return a "default" vertex format for a certain shader data type
	* The simplest vertex format that matches the shader attribute's data type
	*/
	getCompatibleVertexFormat(opts) {
		let vertexType;
		switch (opts.primitiveType) {
			case "f32":
				vertexType = "float32";
				break;
			case "i32":
				vertexType = "sint32";
				break;
			case "u32":
				vertexType = "uint32";
				break;
			case "f16": return opts.components <= 2 ? "float16x2" : "float16x4";
		}
		if (opts.components === 1) return vertexType;
		return `${vertexType}x${opts.components}`;
	}
};
/** Decoder for luma.gl vertex types */
var vertexFormatDecoder = new VertexFormatDecoder();
//#endregion
//#region node_modules/@luma.gl/core/dist/shadertypes/texture-types/texture-format-table.js
var texture_compression_bc = "texture-compression-bc";
var texture_compression_astc = "texture-compression-astc";
var texture_compression_etc2 = "texture-compression-etc2";
var texture_compression_etc1_webgl = "texture-compression-etc1-webgl";
var texture_compression_pvrtc_webgl = "texture-compression-pvrtc-webgl";
var texture_compression_atc_webgl = "texture-compression-atc-webgl";
var float32_renderable = "float32-renderable-webgl";
var float16_renderable = "float16-renderable-webgl";
var rgb9e5ufloat_renderable = "rgb9e5ufloat-renderable-webgl";
var snorm8_renderable = "snorm8-renderable-webgl";
var norm16_webgl = "norm16-webgl";
var norm16_renderable = "norm16-renderable-webgl";
var snorm16_renderable = "snorm16-renderable-webgl";
var float32_filterable = "float32-filterable";
var float16_filterable = "float16-filterable-webgl";
function getTextureFormatDefinition(format) {
	const info = TEXTURE_FORMAT_TABLE[format];
	if (!info) throw new Error(`Unsupported texture format ${format}`);
	return info;
}
function getTextureFormatTable() {
	return TEXTURE_FORMAT_TABLE;
}
var TEXTURE_FORMAT_COLOR_DEPTH_TABLE = {
	"r8unorm": {},
	"rg8unorm": {},
	"rgb8unorm-webgl": {},
	"rgba8unorm": {},
	"rgba8unorm-srgb": {},
	"r8snorm": { render: snorm8_renderable },
	"rg8snorm": { render: snorm8_renderable },
	"rgb8snorm-webgl": {},
	"rgba8snorm": { render: snorm8_renderable },
	"r8uint": {},
	"rg8uint": {},
	"rgba8uint": {},
	"r8sint": {},
	"rg8sint": {},
	"rgba8sint": {},
	"bgra8unorm": {},
	"bgra8unorm-srgb": {},
	"r16unorm": {
		f: norm16_webgl,
		render: norm16_renderable
	},
	"rg16unorm": {
		f: norm16_webgl,
		render: norm16_renderable
	},
	"rgb16unorm-webgl": {
		f: norm16_webgl,
		render: false
	},
	"rgba16unorm": {
		f: norm16_webgl,
		render: norm16_renderable
	},
	"r16snorm": {
		f: norm16_webgl,
		render: snorm16_renderable
	},
	"rg16snorm": {
		f: norm16_webgl,
		render: snorm16_renderable
	},
	"rgb16snorm-webgl": {
		f: norm16_webgl,
		render: false
	},
	"rgba16snorm": {
		f: norm16_webgl,
		render: snorm16_renderable
	},
	"r16uint": {},
	"rg16uint": {},
	"rgba16uint": {},
	"r16sint": {},
	"rg16sint": {},
	"rgba16sint": {},
	"r16float": {
		render: float16_renderable,
		filter: "float16-filterable-webgl"
	},
	"rg16float": {
		render: float16_renderable,
		filter: float16_filterable
	},
	"rgba16float": {
		render: float16_renderable,
		filter: float16_filterable
	},
	"r32uint": {},
	"rg32uint": {},
	"rgba32uint": {},
	"r32sint": {},
	"rg32sint": {},
	"rgba32sint": {},
	"r32float": {
		render: float32_renderable,
		filter: float32_filterable
	},
	"rg32float": {
		render: false,
		filter: float32_filterable
	},
	"rgb32float-webgl": {
		render: float32_renderable,
		filter: float32_filterable
	},
	"rgba32float": {
		render: float32_renderable,
		filter: float32_filterable
	},
	"rgba4unorm-webgl": {
		channels: "rgba",
		bitsPerChannel: [
			4,
			4,
			4,
			4
		],
		packed: true
	},
	"rgb565unorm-webgl": {
		channels: "rgb",
		bitsPerChannel: [
			5,
			6,
			5,
			0
		],
		packed: true
	},
	"rgb5a1unorm-webgl": {
		channels: "rgba",
		bitsPerChannel: [
			5,
			5,
			5,
			1
		],
		packed: true
	},
	"rgb9e5ufloat": {
		channels: "rgb",
		packed: true,
		render: rgb9e5ufloat_renderable
	},
	"rg11b10ufloat": {
		channels: "rgb",
		bitsPerChannel: [
			11,
			11,
			10,
			0
		],
		packed: true,
		p: 1,
		render: float32_renderable
	},
	"rgb10a2unorm": {
		channels: "rgba",
		bitsPerChannel: [
			10,
			10,
			10,
			2
		],
		packed: true,
		p: 1
	},
	"rgb10a2uint": {
		channels: "rgba",
		bitsPerChannel: [
			10,
			10,
			10,
			2
		],
		packed: true,
		p: 1
	},
	stencil8: {
		attachment: "stencil",
		bitsPerChannel: [
			8,
			0,
			0,
			0
		],
		dataType: "uint8"
	},
	"depth16unorm": {
		attachment: "depth",
		bitsPerChannel: [
			16,
			0,
			0,
			0
		],
		dataType: "uint16"
	},
	"depth24plus": {
		attachment: "depth",
		bitsPerChannel: [
			24,
			0,
			0,
			0
		],
		dataType: "uint32"
	},
	"depth32float": {
		attachment: "depth",
		bitsPerChannel: [
			32,
			0,
			0,
			0
		],
		dataType: "float32"
	},
	"depth24plus-stencil8": {
		attachment: "depth-stencil",
		bitsPerChannel: [
			24,
			8,
			0,
			0
		],
		packed: true
	},
	"depth32float-stencil8": {
		attachment: "depth-stencil",
		bitsPerChannel: [
			32,
			8,
			0,
			0
		],
		packed: true
	}
};
var TEXTURE_FORMAT_COMPRESSED_TABLE = {
	"bc1-rgb-unorm-webgl": { f: texture_compression_bc },
	"bc1-rgb-unorm-srgb-webgl": { f: texture_compression_bc },
	"bc1-rgba-unorm": { f: texture_compression_bc },
	"bc1-rgba-unorm-srgb": { f: texture_compression_bc },
	"bc2-rgba-unorm": { f: texture_compression_bc },
	"bc2-rgba-unorm-srgb": { f: texture_compression_bc },
	"bc3-rgba-unorm": { f: texture_compression_bc },
	"bc3-rgba-unorm-srgb": { f: texture_compression_bc },
	"bc4-r-unorm": { f: texture_compression_bc },
	"bc4-r-snorm": { f: texture_compression_bc },
	"bc5-rg-unorm": { f: texture_compression_bc },
	"bc5-rg-snorm": { f: texture_compression_bc },
	"bc6h-rgb-ufloat": { f: texture_compression_bc },
	"bc6h-rgb-float": { f: texture_compression_bc },
	"bc7-rgba-unorm": { f: texture_compression_bc },
	"bc7-rgba-unorm-srgb": { f: texture_compression_bc },
	"etc2-rgb8unorm": { f: texture_compression_etc2 },
	"etc2-rgb8unorm-srgb": { f: texture_compression_etc2 },
	"etc2-rgb8a1unorm": { f: texture_compression_etc2 },
	"etc2-rgb8a1unorm-srgb": { f: texture_compression_etc2 },
	"etc2-rgba8unorm": { f: texture_compression_etc2 },
	"etc2-rgba8unorm-srgb": { f: texture_compression_etc2 },
	"eac-r11unorm": { f: texture_compression_etc2 },
	"eac-r11snorm": { f: texture_compression_etc2 },
	"eac-rg11unorm": { f: texture_compression_etc2 },
	"eac-rg11snorm": { f: texture_compression_etc2 },
	"astc-4x4-unorm": { f: texture_compression_astc },
	"astc-4x4-unorm-srgb": { f: texture_compression_astc },
	"astc-5x4-unorm": { f: texture_compression_astc },
	"astc-5x4-unorm-srgb": { f: texture_compression_astc },
	"astc-5x5-unorm": { f: texture_compression_astc },
	"astc-5x5-unorm-srgb": { f: texture_compression_astc },
	"astc-6x5-unorm": { f: texture_compression_astc },
	"astc-6x5-unorm-srgb": { f: texture_compression_astc },
	"astc-6x6-unorm": { f: texture_compression_astc },
	"astc-6x6-unorm-srgb": { f: texture_compression_astc },
	"astc-8x5-unorm": { f: texture_compression_astc },
	"astc-8x5-unorm-srgb": { f: texture_compression_astc },
	"astc-8x6-unorm": { f: texture_compression_astc },
	"astc-8x6-unorm-srgb": { f: texture_compression_astc },
	"astc-8x8-unorm": { f: texture_compression_astc },
	"astc-8x8-unorm-srgb": { f: texture_compression_astc },
	"astc-10x5-unorm": { f: texture_compression_astc },
	"astc-10x5-unorm-srgb": { f: texture_compression_astc },
	"astc-10x6-unorm": { f: texture_compression_astc },
	"astc-10x6-unorm-srgb": { f: texture_compression_astc },
	"astc-10x8-unorm": { f: texture_compression_astc },
	"astc-10x8-unorm-srgb": { f: texture_compression_astc },
	"astc-10x10-unorm": { f: texture_compression_astc },
	"astc-10x10-unorm-srgb": { f: texture_compression_astc },
	"astc-12x10-unorm": { f: texture_compression_astc },
	"astc-12x10-unorm-srgb": { f: texture_compression_astc },
	"astc-12x12-unorm": { f: texture_compression_astc },
	"astc-12x12-unorm-srgb": { f: texture_compression_astc },
	"pvrtc-rgb4unorm-webgl": { f: texture_compression_pvrtc_webgl },
	"pvrtc-rgba4unorm-webgl": { f: texture_compression_pvrtc_webgl },
	"pvrtc-rgb2unorm-webgl": { f: texture_compression_pvrtc_webgl },
	"pvrtc-rgba2unorm-webgl": { f: texture_compression_pvrtc_webgl },
	"etc1-rbg-unorm-webgl": { f: texture_compression_etc1_webgl },
	"atc-rgb-unorm-webgl": { f: texture_compression_atc_webgl },
	"atc-rgba-unorm-webgl": { f: texture_compression_atc_webgl },
	"atc-rgbai-unorm-webgl": { f: texture_compression_atc_webgl }
};
var TEXTURE_FORMAT_TABLE = {
	...TEXTURE_FORMAT_COLOR_DEPTH_TABLE,
	...TEXTURE_FORMAT_COMPRESSED_TABLE
};
//#endregion
//#region node_modules/@luma.gl/core/dist/shadertypes/texture-types/texture-format-decoder.js
var RGB_FORMAT_REGEX = /^(r|rg|rgb|rgba|bgra)([0-9]*)([a-z]*)(-srgb)?(-webgl)?$/;
var COLOR_FORMAT_PREFIXES = [
	"rgb",
	"rgba",
	"bgra"
];
var DEPTH_FORMAT_PREFIXES = ["depth", "stencil"];
var COMPRESSED_TEXTURE_FORMAT_PREFIXES = [
	"bc1",
	"bc2",
	"bc3",
	"bc4",
	"bc5",
	"bc6",
	"bc7",
	"etc1",
	"etc2",
	"eac",
	"atc",
	"astc",
	"pvrtc"
];
/** Class that helps applications work with texture formats */
var TextureFormatDecoder = class {
	/** Checks if a texture format is color */
	isColor(format) {
		return COLOR_FORMAT_PREFIXES.some((prefix) => format.startsWith(prefix));
	}
	/** Checks if a texture format is depth or stencil */
	isDepthStencil(format) {
		return DEPTH_FORMAT_PREFIXES.some((prefix) => format.startsWith(prefix));
	}
	/** Checks if a texture format is compressed */
	isCompressed(format) {
		return COMPRESSED_TEXTURE_FORMAT_PREFIXES.some((prefix) => format.startsWith(prefix));
	}
	/** Returns information about a texture format, e.g. attachment type, components, byte length and flags (integer, signed, normalized) */
	getInfo(format) {
		return getTextureFormatInfo(format);
	}
	/**  "static" capabilities of a texture format. @note Needs to be adjusted against current device */
	getCapabilities(format) {
		return getTextureFormatCapabilities(format);
	}
	/** Computes the memory layout for a texture, in particular including row byte alignment */
	computeMemoryLayout(opts) {
		return computeTextureMemoryLayout(opts);
	}
};
/** Decoder for luma.gl texture types */
var textureFormatDecoder = new TextureFormatDecoder();
/** Get the memory layout of a texture */
function computeTextureMemoryLayout({ format, width, height, depth, byteAlignment }) {
	const { bytesPerPixel, bytesPerBlock = bytesPerPixel, blockWidth = 1, blockHeight = 1, compressed = false } = textureFormatDecoder.getInfo(format);
	const blockColumns = compressed ? Math.ceil(width / blockWidth) : width;
	const blockRows = compressed ? Math.ceil(height / blockHeight) : height;
	const unpaddedBytesPerRow = blockColumns * bytesPerBlock;
	const bytesPerRow = Math.ceil(unpaddedBytesPerRow / byteAlignment) * byteAlignment;
	const rowsPerImage = blockRows;
	const byteLength = bytesPerRow * rowsPerImage * depth;
	return {
		bytesPerPixel,
		bytesPerRow,
		rowsPerImage,
		depthOrArrayLayers: depth,
		bytesPerImage: bytesPerRow * rowsPerImage,
		byteLength
	};
}
function getTextureFormatCapabilities(format) {
	const info = getTextureFormatDefinition(format);
	const formatCapabilities = {
		format,
		create: info.f ?? true,
		render: info.render ?? true,
		filter: info.filter ?? true,
		blend: info.blend ?? true,
		store: info.store ?? true
	};
	const formatInfo = getTextureFormatInfo(format);
	const isDepthStencil = format.startsWith("depth") || format.startsWith("stencil");
	const isSigned = formatInfo?.signed;
	const isInteger = formatInfo?.integer;
	const isWebGLSpecific = formatInfo?.webgl;
	const isCompressed = Boolean(formatInfo?.compressed);
	formatCapabilities.render &&= !isDepthStencil && !isCompressed;
	formatCapabilities.filter &&= !isDepthStencil && !isSigned && !isInteger && !isWebGLSpecific;
	return formatCapabilities;
}
/**
* Decodes a texture format, returning e.g. attatchment type, components, byte length and flags (integer, signed, normalized)
*/
function getTextureFormatInfo(format) {
	let formatInfo = getTextureFormatInfoUsingTable(format);
	if (textureFormatDecoder.isCompressed(format)) {
		formatInfo.channels = "rgb";
		formatInfo.components = 3;
		formatInfo.bytesPerPixel = 1;
		formatInfo.srgb = false;
		formatInfo.compressed = true;
		formatInfo.bytesPerBlock = getCompressedTextureBlockByteLength(format);
		const blockSize = getCompressedTextureBlockSize(format);
		if (blockSize) {
			formatInfo.blockWidth = blockSize.blockWidth;
			formatInfo.blockHeight = blockSize.blockHeight;
		}
	}
	const matches = !formatInfo.packed ? RGB_FORMAT_REGEX.exec(format) : null;
	if (matches) {
		const [, channels, length, type, srgb, suffix] = matches;
		const dataType = `${type}${length}`;
		const decodedType = dataTypeDecoder.getDataTypeInfo(dataType);
		const bits = decodedType.byteLength * 8;
		const components = channels?.length ?? 1;
		const bitsPerChannel = [
			bits,
			components >= 2 ? bits : 0,
			components >= 3 ? bits : 0,
			components >= 4 ? bits : 0
		];
		formatInfo = {
			format,
			attachment: formatInfo.attachment,
			dataType: decodedType.signedType,
			components,
			channels,
			integer: decodedType.integer,
			signed: decodedType.signed,
			normalized: decodedType.normalized,
			bitsPerChannel,
			bytesPerPixel: decodedType.byteLength * components,
			packed: formatInfo.packed,
			srgb: formatInfo.srgb
		};
		if (suffix === "-webgl") formatInfo.webgl = true;
		if (srgb === "-srgb") formatInfo.srgb = true;
	}
	if (format.endsWith("-webgl")) formatInfo.webgl = true;
	if (format.endsWith("-srgb")) formatInfo.srgb = true;
	return formatInfo;
}
/** Decode texture format info from the table */
function getTextureFormatInfoUsingTable(format) {
	const info = getTextureFormatDefinition(format);
	const bytesPerPixel = info.bytesPerPixel || 1;
	const bitsPerChannel = info.bitsPerChannel || [
		8,
		8,
		8,
		8
	];
	delete info.bitsPerChannel;
	delete info.bytesPerPixel;
	delete info.f;
	delete info.render;
	delete info.filter;
	delete info.blend;
	delete info.store;
	return {
		...info,
		format,
		attachment: info.attachment || "color",
		channels: info.channels || "r",
		components: info.components || info.channels?.length || 1,
		bytesPerPixel,
		bitsPerChannel,
		dataType: info.dataType || "uint8",
		srgb: info.srgb ?? false,
		packed: info.packed ?? false,
		webgl: info.webgl ?? false,
		integer: info.integer ?? false,
		signed: info.signed ?? false,
		normalized: info.normalized ?? false,
		compressed: info.compressed ?? false
	};
}
/** Parses ASTC block widths from format string */
function getCompressedTextureBlockSize(format) {
	const matches = /.*-(\d+)x(\d+)-.*/.exec(format);
	if (matches) {
		const [, blockWidth, blockHeight] = matches;
		return {
			blockWidth: Number(blockWidth),
			blockHeight: Number(blockHeight)
		};
	}
	if (format.startsWith("bc") || format.startsWith("etc1") || format.startsWith("etc2") || format.startsWith("eac") || format.startsWith("atc")) return {
		blockWidth: 4,
		blockHeight: 4
	};
	if (format.startsWith("pvrtc-rgb4") || format.startsWith("pvrtc-rgba4")) return {
		blockWidth: 4,
		blockHeight: 4
	};
	if (format.startsWith("pvrtc-rgb2") || format.startsWith("pvrtc-rgba2")) return {
		blockWidth: 8,
		blockHeight: 4
	};
	return null;
}
function getCompressedTextureBlockByteLength(format) {
	if (format.startsWith("bc1") || format.startsWith("bc4") || format.startsWith("etc1") || format.startsWith("etc2-rgb8") || format.startsWith("etc2-rgb8a1") || format.startsWith("eac-r11") || format === "atc-rgb-unorm-webgl") return 8;
	if (format.startsWith("bc2") || format.startsWith("bc3") || format.startsWith("bc5") || format.startsWith("bc6h") || format.startsWith("bc7") || format.startsWith("etc2-rgba8") || format.startsWith("eac-rg11") || format.startsWith("astc") || format === "atc-rgba-unorm-webgl" || format === "atc-rgbai-unorm-webgl") return 16;
	if (format.startsWith("pvrtc")) return 8;
	return 16;
}
//#endregion
//#region node_modules/@luma.gl/core/dist/shadertypes/image-types/image-types.js
/** Check if data is an external image */
function isExternalImage(data) {
	return typeof ImageData !== "undefined" && data instanceof ImageData || typeof ImageBitmap !== "undefined" && data instanceof ImageBitmap || typeof HTMLImageElement !== "undefined" && data instanceof HTMLImageElement || typeof HTMLVideoElement !== "undefined" && data instanceof HTMLVideoElement || typeof VideoFrame !== "undefined" && data instanceof VideoFrame || typeof HTMLCanvasElement !== "undefined" && data instanceof HTMLCanvasElement || typeof OffscreenCanvas !== "undefined" && data instanceof OffscreenCanvas;
}
/** Determine size (width and height) of provided image data */
function getExternalImageSize(data) {
	if (typeof ImageData !== "undefined" && data instanceof ImageData || typeof ImageBitmap !== "undefined" && data instanceof ImageBitmap || typeof HTMLCanvasElement !== "undefined" && data instanceof HTMLCanvasElement || typeof OffscreenCanvas !== "undefined" && data instanceof OffscreenCanvas) return {
		width: data.width,
		height: data.height
	};
	if (typeof HTMLImageElement !== "undefined" && data instanceof HTMLImageElement) return {
		width: data.naturalWidth,
		height: data.naturalHeight
	};
	if (typeof HTMLVideoElement !== "undefined" && data instanceof HTMLVideoElement) return {
		width: data.videoWidth,
		height: data.videoHeight
	};
	if (typeof VideoFrame !== "undefined" && data instanceof VideoFrame) return {
		width: data.displayWidth,
		height: data.displayHeight
	};
	throw new Error("Unknown image type");
}
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/device.js
/** Limits for a device (max supported sizes of resources, max number of bindings etc) */
var DeviceLimits = class {};
function formatErrorLogArguments(context, args) {
	return [formatErrorLogValue(context), ...args.map(formatErrorLogValue).filter((arg) => arg !== void 0)].filter((arg) => arg !== void 0);
}
function formatErrorLogValue(value) {
	if (value === void 0) return;
	if (value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean") return value;
	if (value instanceof Error) return value.message;
	if (Array.isArray(value)) return value.map(formatErrorLogValue);
	if (typeof value === "object") {
		if (hasCustomToString(value)) {
			const stringValue = String(value);
			if (stringValue !== "[object Object]") return stringValue;
		}
		if (looksLikeGPUCompilationMessage(value)) return formatGPUCompilationMessage(value);
		return value.constructor?.name || "Object";
	}
	return String(value);
}
function hasCustomToString(value) {
	return "toString" in value && typeof value.toString === "function" && value.toString !== Object.prototype.toString;
}
function looksLikeGPUCompilationMessage(value) {
	return "message" in value && "type" in value;
}
function formatGPUCompilationMessage(value) {
	const type = typeof value.type === "string" ? value.type : "message";
	const message = typeof value.message === "string" ? value.message : "";
	const lineNum = typeof value.lineNum === "number" ? value.lineNum : null;
	const linePos = typeof value.linePos === "number" ? value.linePos : null;
	return `${type}${lineNum !== null && linePos !== null ? ` @ ${lineNum}:${linePos}` : lineNum !== null ? ` @ ${lineNum}` : ""}: ${message}`.trim();
}
/** Set-like class for features (lets apps check for WebGL / WebGPU extensions) */
var DeviceFeatures = class {
	features;
	disabledFeatures;
	constructor(features = [], disabledFeatures) {
		this.features = new Set(features);
		this.disabledFeatures = disabledFeatures || {};
	}
	*[Symbol.iterator]() {
		yield* this.features;
	}
	has(feature) {
		return !this.disabledFeatures?.[feature] && this.features.has(feature);
	}
};
/**
* WebGPU Device/WebGL context abstraction
*/
var Device = class Device {
	static defaultProps = {
		id: null,
		powerPreference: "high-performance",
		failIfMajorPerformanceCaveat: false,
		createCanvasContext: void 0,
		webgl: {},
		onError: (error, context) => {},
		onResize: (context, info) => {
			const [width, height] = context.getDevicePixelSize();
			log.log(1, `${context} resized => ${width}x${height}px`)();
		},
		onPositionChange: (context, info) => {
			const [left, top] = context.getPosition();
			log.log(1, `${context} repositioned => ${left},${top}`)();
		},
		onVisibilityChange: (context) => log.log(1, `${context} Visibility changed ${context.isVisible}`)(),
		onDevicePixelRatioChange: (context, info) => log.log(1, `${context} DPR changed ${info.oldRatio} => ${context.devicePixelRatio}`)(),
		debug: getDefaultDebugValue(),
		debugGPUTime: false,
		debugShaders: log.get("debug-shaders") || void 0,
		debugFramebuffers: Boolean(log.get("debug-framebuffers")),
		debugFactories: Boolean(log.get("debug-factories")),
		debugWebGL: Boolean(log.get("debug-webgl")),
		debugSpectorJS: void 0,
		debugSpectorJSUrl: void 0,
		_reuseDevices: false,
		_requestMaxLimits: true,
		_cacheShaders: true,
		_destroyShaders: false,
		_cachePipelines: true,
		_sharePipelines: true,
		_destroyPipelines: false,
		_initializeFeatures: true,
		_disabledFeatures: { "compilation-status-async-webgl": true },
		_handle: void 0
	};
	get [Symbol.toStringTag]() {
		return "Device";
	}
	toString() {
		return `Device(${this.id})`;
	}
	/** id of this device, primarily for debugging */
	id;
	/** A copy of the device props  */
	props;
	/** Available for the application to store data on the device */
	userData = {};
	/** stats */
	statsManager = lumaStats;
	/** Internal per-device factory storage */
	_factories = {};
	/** An abstract timestamp used for change tracking */
	timestamp = 0;
	/** True if this device has been reused during device creation (app has multiple references) */
	_reused = false;
	/** Used by other luma.gl modules to store data on the device */
	_moduleData = {};
	_textureCaps = {};
	/** Internal timestamp query set used when GPU timing collection is enabled for this device. */
	_debugGPUTimeQuery = null;
	constructor(props) {
		this.props = {
			...Device.defaultProps,
			...props
		};
		this.id = this.props.id || uid(this[Symbol.toStringTag].toLowerCase());
	}
	getVertexFormatInfo(format) {
		return vertexFormatDecoder.getVertexFormatInfo(format);
	}
	isVertexFormatSupported(format) {
		return true;
	}
	/** Returns information about a texture format, such as data type, channels, bits per channel, compression etc */
	getTextureFormatInfo(format) {
		return textureFormatDecoder.getInfo(format);
	}
	/** Determines what operations are supported on a texture format on this particular device (checks against supported device features) */
	getTextureFormatCapabilities(format) {
		let textureCaps = this._textureCaps[format];
		if (!textureCaps) {
			const capabilities = this._getDeviceTextureFormatCapabilities(format);
			textureCaps = this._getDeviceSpecificTextureFormatCapabilities(capabilities);
			this._textureCaps[format] = textureCaps;
		}
		return textureCaps;
	}
	/** Calculates the number of mip levels for a texture of width, height and in case of 3d textures only, depth */
	getMipLevelCount(width, height, depth3d = 1) {
		return 1 + Math.floor(Math.log2(Math.max(width, height, depth3d)));
	}
	/** Check if data is an external image */
	isExternalImage(data) {
		return isExternalImage(data);
	}
	/** Get the size of an external image */
	getExternalImageSize(data) {
		return getExternalImageSize(data);
	}
	/** Check if device supports a specific texture format (creation and `nearest` sampling) */
	isTextureFormatSupported(format) {
		return this.getTextureFormatCapabilities(format).create;
	}
	/** Check if linear filtering (sampler interpolation) is supported for a specific texture format */
	isTextureFormatFilterable(format) {
		return this.getTextureFormatCapabilities(format).filter;
	}
	/** Check if device supports rendering to a framebuffer color attachment of a specific texture format */
	isTextureFormatRenderable(format) {
		return this.getTextureFormatCapabilities(format).render;
	}
	/** Check if a specific texture format is GPU compressed */
	isTextureFormatCompressed(format) {
		return textureFormatDecoder.isCompressed(format);
	}
	/** Returns the compressed texture formats that can be created and sampled on this device */
	getSupportedCompressedTextureFormats() {
		const supportedFormats = [];
		for (const format of Object.keys(getTextureFormatTable())) if (this.isTextureFormatCompressed(format) && this.isTextureFormatSupported(format)) supportedFormats.push(format);
		return supportedFormats;
	}
	pushDebugGroup(groupLabel) {
		this.commandEncoder.pushDebugGroup(groupLabel);
	}
	popDebugGroup() {
		this.commandEncoder?.popDebugGroup();
	}
	insertDebugMarker(markerLabel) {
		this.commandEncoder?.insertDebugMarker(markerLabel);
	}
	/**
	* Trigger device loss.
	* @returns `true` if context loss could actually be triggered.
	* @note primarily intended for testing how application reacts to device loss
	*/
	loseDevice() {
		return false;
	}
	/** A monotonic counter for tracking buffer and texture updates */
	incrementTimestamp() {
		return this.timestamp++;
	}
	/**
	* Reports Device errors in a way that optimizes for developer experience / debugging.
	* - Logs so that the console error links directly to the source code that generated the error.
	* - Includes the object that reported the error in the log message, even if the error is asynchronous.
	*
	* Conventions when calling reportError():
	* - Always call the returned function - to ensure error is logged, at the error site
	* - Follow with a call to device.debug() - to ensure that the debugger breaks at the error site
	*
	* @param error - the error to report. If needed, just create a new Error object with the appropriate message.
	* @param context - pass `this` as context, otherwise it may not be available in the debugger for async errors.
	* @returns the logger function returned by device.props.onError() so that it can be called from the error site.
	*
	* @example
	*   device.reportError(new Error(...), this)();
	*   device.debug();
	*/
	reportError(error, context, ...args) {
		if (!this.props.onError(error, context)) {
			const logArguments = formatErrorLogArguments(context, args);
			return log.error(this.type === "webgl" ? "%cWebGL" : "%cWebGPU", "color: white; background: red; padding: 2px 6px; border-radius: 3px;", error.message, ...logArguments);
		}
		return () => {};
	}
	/** Break in the debugger - if device.props.debug is true */
	debug() {
		if (this.props.debug) debugger;
		else log.once(0, `\
'Type luma.log.set({debug: true}) in console to enable debug breakpoints',
or create a device with the 'debug: true' prop.`)();
	}
	/** Returns the default / primary canvas context. Throws an error if no canvas context is available (a WebGPU compute device) */
	getDefaultCanvasContext() {
		if (!this.canvasContext) throw new Error("Device has no default CanvasContext. See props.createCanvasContext");
		return this.canvasContext;
	}
	/** Create a fence sync object */
	createFence() {
		throw new Error("createFence() not implemented");
	}
	/** Create a RenderPass using the default CommandEncoder */
	beginRenderPass(props) {
		return this.commandEncoder.beginRenderPass(props);
	}
	/** Create a ComputePass using the default CommandEncoder*/
	beginComputePass(props) {
		return this.commandEncoder.beginComputePass(props);
	}
	/**
	* Generate mipmaps for a WebGPU texture.
	* WebGPU textures must be created up front with the required mip count, usage flags, and a format that supports the chosen generation path.
	* WebGL uses `Texture.generateMipmapsWebGL()` directly because the backend manages mip generation on the texture object itself.
	*/
	generateMipmapsWebGPU(_texture) {
		throw new Error("not implemented");
	}
	/** Internal helper for creating a shareable WebGL render-pipeline implementation. */
	_createSharedRenderPipelineWebGL(_props) {
		throw new Error("_createSharedRenderPipelineWebGL() not implemented");
	}
	/** Internal WebGPU-only helper for retrieving the native bind-group layout for a pipeline group. */
	_createBindGroupLayoutWebGPU(_pipeline, _group) {
		throw new Error("_createBindGroupLayoutWebGPU() not implemented");
	}
	/** Internal WebGPU-only helper for creating a native bind group. */
	_createBindGroupWebGPU(_bindGroupLayout, _shaderLayout, _bindings, _group, _label) {
		throw new Error("_createBindGroupWebGPU() not implemented");
	}
	/**
	* Internal helper that returns `true` when timestamp-query GPU timing should be
	* collected for this device.
	*/
	_supportsDebugGPUTime() {
		return this.features.has("timestamp-query") && Boolean(this.props.debug || this.props.debugGPUTime);
	}
	/**
	* Internal helper that enables device-managed GPU timing collection on the
	* default command encoder. Reuses the existing query set if timing is already enabled.
	*
	* @param queryCount - Number of timestamp slots reserved for profiled passes.
	* @returns The device-managed timestamp QuerySet, or `null` when timing is not supported or could not be enabled.
	*/
	_enableDebugGPUTime(queryCount = 256) {
		if (!this._supportsDebugGPUTime()) return null;
		if (this._debugGPUTimeQuery) return this._debugGPUTimeQuery;
		try {
			this._debugGPUTimeQuery = this.createQuerySet({
				type: "timestamp",
				count: queryCount
			});
			this.commandEncoder = this.createCommandEncoder({
				id: this.commandEncoder.props.id,
				timeProfilingQuerySet: this._debugGPUTimeQuery
			});
		} catch {
			this._debugGPUTimeQuery = null;
		}
		return this._debugGPUTimeQuery;
	}
	/**
	* Internal helper that disables device-managed GPU timing collection and restores
	* the default command encoder to an unprofiled state.
	*/
	_disableDebugGPUTime() {
		if (!this._debugGPUTimeQuery) return;
		if (this.commandEncoder.getTimeProfilingQuerySet() === this._debugGPUTimeQuery) this.commandEncoder = this.createCommandEncoder({ id: this.commandEncoder.props.id });
		this._debugGPUTimeQuery.destroy();
		this._debugGPUTimeQuery = null;
	}
	/** Internal helper that returns `true` when device-managed GPU timing is currently active. */
	_isDebugGPUTimeEnabled() {
		return this._debugGPUTimeQuery !== null;
	}
	/** @deprecated Use getDefaultCanvasContext() */
	getCanvasContext() {
		return this.getDefaultCanvasContext();
	}
	/** @deprecated - will be removed - should use command encoder */
	readPixelsToArrayWebGL(source, options) {
		throw new Error("not implemented");
	}
	/** @deprecated - will be removed - should use command encoder */
	readPixelsToBufferWebGL(source, options) {
		throw new Error("not implemented");
	}
	/** @deprecated - will be removed - should use WebGPU parameters (pipeline) */
	setParametersWebGL(parameters) {
		throw new Error("not implemented");
	}
	/** @deprecated - will be removed - should use WebGPU parameters (pipeline) */
	getParametersWebGL(parameters) {
		throw new Error("not implemented");
	}
	/** @deprecated - will be removed - should use WebGPU parameters (pipeline) */
	withParametersWebGL(parameters, func) {
		throw new Error("not implemented");
	}
	/** @deprecated - will be removed - should use clear arguments in RenderPass */
	clearWebGL(options) {
		throw new Error("not implemented");
	}
	/** @deprecated - will be removed - should use for debugging only */
	resetWebGL() {
		throw new Error("not implemented");
	}
	getModuleData(moduleName) {
		this._moduleData[moduleName] ||= {};
		return this._moduleData[moduleName];
	}
	/** Helper to get the canvas context props */
	static _getCanvasContextProps(props) {
		return props.createCanvasContext === true ? {} : props.createCanvasContext;
	}
	_getDeviceTextureFormatCapabilities(format) {
		const genericCapabilities = textureFormatDecoder.getCapabilities(format);
		const checkFeature = (feature) => (typeof feature === "string" ? this.features.has(feature) : feature) ?? true;
		const supported = checkFeature(genericCapabilities.create);
		return {
			format,
			create: supported,
			render: supported && checkFeature(genericCapabilities.render),
			filter: supported && checkFeature(genericCapabilities.filter),
			blend: supported && checkFeature(genericCapabilities.blend),
			store: supported && checkFeature(genericCapabilities.store)
		};
	}
	/** Subclasses use this to support .createBuffer() overloads */
	_normalizeBufferProps(props) {
		if (props instanceof ArrayBuffer || ArrayBuffer.isView(props)) props = { data: props };
		const newProps = { ...props };
		if ((props.usage || 0) & Buffer.INDEX) {
			if (!props.indexType) {
				if (props.data instanceof Uint32Array) newProps.indexType = "uint32";
				else if (props.data instanceof Uint16Array) newProps.indexType = "uint16";
				else if (props.data instanceof Uint8Array) {
					newProps.data = new Uint16Array(props.data);
					newProps.indexType = "uint16";
				}
			}
			if (!newProps.indexType) throw new Error("indices buffer content must be of type uint16 or uint32");
		}
		return newProps;
	}
};
/**
* Internal helper for resolving the default `debug` prop.
* Precedence is: explicit log debug value first, then `NODE_ENV`, then `false`.
*/
function _getDefaultDebugValue(logDebugValue, nodeEnv) {
	if (logDebugValue !== void 0 && logDebugValue !== null) return Boolean(logDebugValue);
	if (nodeEnv !== void 0) return nodeEnv !== "production";
	return false;
}
function getDefaultDebugValue() {
	return _getDefaultDebugValue(log.get("debug"), getNodeEnv());
}
function getNodeEnv() {
	const processObject = globalThis.process;
	if (!processObject?.env) return;
	return processObject.env["NODE_ENV"];
}
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/resources/sampler.js
/** Immutable Sampler object */
var Sampler = class Sampler extends Resource {
	static defaultProps = {
		...Resource.defaultProps,
		type: "color-sampler",
		addressModeU: "clamp-to-edge",
		addressModeV: "clamp-to-edge",
		addressModeW: "clamp-to-edge",
		magFilter: "nearest",
		minFilter: "nearest",
		mipmapFilter: "none",
		lodMinClamp: 0,
		lodMaxClamp: 32,
		compare: "less-equal",
		maxAnisotropy: 1
	};
	get [Symbol.toStringTag]() {
		return "Sampler";
	}
	constructor(device, props) {
		props = Sampler.normalizeProps(device, props);
		super(device, props, Sampler.defaultProps);
	}
	static normalizeProps(device, props) {
		return props;
	}
};
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/resources/texture.js
var BASE_DIMENSIONS = {
	"1d": "1d",
	"2d": "2d",
	"2d-array": "2d",
	cube: "2d",
	"cube-array": "2d",
	"3d": "3d"
};
/**
* Abstract Texture interface
* Texture Object
* https://gpuweb.github.io/gpuweb/#gputexture
*/
var Texture = class Texture extends Resource {
	/** The texture can be bound for use as a sampled texture in a shader */
	static SAMPLE = 4;
	/** The texture can be bound for use as a storage texture in a shader */
	static STORAGE = 8;
	/** The texture can be used as a color or depth/stencil attachment in a render pass */
	static RENDER = 16;
	/** The texture can be used as the source of a copy operation */
	static COPY_SRC = 1;
	/** he texture can be used as the destination of a copy or write operation */
	static COPY_DST = 2;
	/** @deprecated Use Texture.SAMPLE */
	static TEXTURE = 4;
	/** @deprecated Use Texture.RENDER */
	static RENDER_ATTACHMENT = 16;
	/** dimension of this texture */
	dimension;
	/** base dimension of this texture */
	baseDimension;
	/** format of this texture */
	format;
	/** width in pixels of this texture */
	width;
	/** height in pixels of this texture */
	height;
	/** depth of this texture */
	depth;
	/** mip levels in this texture */
	mipLevels;
	/** sample count */
	samples;
	/** Rows are multiples of this length, padded with extra bytes if needed */
	byteAlignment;
	/** The ready promise is always resolved. It is provided for type compatibility with DynamicTexture. */
	ready = Promise.resolve(this);
	/** isReady is always true. It is provided for type compatibility with DynamicTexture. */
	isReady = true;
	/** "Time" of last update. Monotonically increasing timestamp. TODO move to DynamicTexture? */
	updateTimestamp;
	get [Symbol.toStringTag]() {
		return "Texture";
	}
	toString() {
		return `Texture(${this.id},${this.format},${this.width}x${this.height})`;
	}
	/** Do not use directly. Create with device.createTexture() */
	constructor(device, props, backendProps) {
		props = Texture.normalizeProps(device, props);
		super(device, props, Texture.defaultProps);
		this.dimension = this.props.dimension;
		this.baseDimension = BASE_DIMENSIONS[this.dimension];
		this.format = this.props.format;
		this.width = this.props.width;
		this.height = this.props.height;
		this.depth = this.props.depth;
		this.mipLevels = this.props.mipLevels;
		this.samples = this.props.samples || 1;
		if (this.dimension === "cube") this.depth = 6;
		if (this.props.width === void 0 || this.props.height === void 0) if (device.isExternalImage(props.data)) {
			const size = device.getExternalImageSize(props.data);
			this.width = size?.width || 1;
			this.height = size?.height || 1;
		} else {
			this.width = 1;
			this.height = 1;
			if (this.props.width === void 0 || this.props.height === void 0) log.warn(`${this} created with undefined width or height. This is deprecated. Use DynamicTexture instead.`)();
		}
		this.byteAlignment = backendProps?.byteAlignment || 1;
		this.updateTimestamp = device.incrementTimestamp();
	}
	/**
	* Create a new texture with the same parameters and optionally a different size
	* @note Textures are immutable and cannot be resized after creation, but we can create a similar texture with the same parameters but a new size.
	* @note Does not copy contents of the texture
	*/
	clone(size) {
		return this.device.createTexture({
			...this.props,
			...size
		});
	}
	/** Set sampler props associated with this texture */
	setSampler(sampler) {
		this.sampler = sampler instanceof Sampler ? sampler : this.device.createSampler(sampler);
	}
	/**
	* Copy raw image data (bytes) into the texture.
	*
	* @note Deprecated compatibility wrapper over {@link writeData}.
	* @note Uses the same layout defaults and alignment rules as {@link writeData}.
	* @note Tightly packed CPU uploads can omit `bytesPerRow` and `rowsPerImage`.
	* @note If the CPU source rows are padded, pass explicit `bytesPerRow` and `rowsPerImage`.
	* @deprecated Use writeData()
	*/
	copyImageData(options) {
		const { data, depth, ...writeOptions } = options;
		this.writeData(data, {
			...writeOptions,
			depthOrArrayLayers: writeOptions.depthOrArrayLayers ?? depth
		});
	}
	/**
	* Calculates the memory layout of the texture, required when reading and writing data.
	* @return the backend-aligned linear layout, in particular bytesPerRow which includes any required padding for buffer copy/read paths
	*/
	computeMemoryLayout(options_ = {}) {
		const { width = this.width, height = this.height, depthOrArrayLayers = this.depth } = this._normalizeTextureReadOptions(options_);
		const { format, byteAlignment } = this;
		return textureFormatDecoder.computeMemoryLayout({
			format,
			width,
			height,
			depth: depthOrArrayLayers,
			byteAlignment
		});
	}
	/**
	* Read the contents of a texture into a GPU Buffer.
	* @returns A Buffer containing the texture data.
	*
	* @note The memory layout of the texture data is determined by the texture format and dimensions.
	* @note The application can call Texture.computeMemoryLayout() to compute the backend-aligned layout.
	* @note The application can call Buffer.readAsync() to read the returned buffer on the CPU.
	* @note The destination buffer must be supplied by the caller and must be large enough for the requested region.
	* @note On WebGPU this corresponds to a texture-to-buffer copy and uses buffer-copy alignment rules.
	* @note On WebGL, luma.gl emulates the same logical readback behavior.
	*/
	readBuffer(options, buffer) {
		throw new Error("readBuffer not implemented");
	}
	/**
	* Reads data from a texture into an ArrayBuffer.
	* @returns An ArrayBuffer containing the texture data.
	*
	* @note The memory layout of the texture data is determined by the texture format and dimensions.
	* @note The application can call Texture.computeMemoryLayout() to compute the layout.
	* @deprecated Use Texture.readBuffer() with an explicit destination buffer, or DynamicTexture.readAsync() for convenience readback.
	*/
	readDataAsync(options) {
		throw new Error("readBuffer not implemented");
	}
	/**
	* Writes a GPU Buffer into a texture.
	*
	* @param buffer - Source GPU buffer.
	* @param options - Destination subresource, extent, and source layout options.
	* @note The memory layout of the texture data is determined by the texture format and dimensions.
	* @note The application can call Texture.computeMemoryLayout() to compute the backend-aligned layout.
	* @note On WebGPU this corresponds to a buffer-to-texture copy and uses buffer-copy alignment rules.
	* @note On WebGL, luma.gl emulates the same destination and layout semantics.
	*/
	writeBuffer(buffer, options) {
		throw new Error("readBuffer not implemented");
	}
	/**
	* Writes an array buffer into a texture.
	*
	* @param data - Source texel data.
	* @param options - Destination subresource, extent, and source layout options.
	* @note If `bytesPerRow` and `rowsPerImage` are omitted, luma.gl computes a tightly packed CPU-memory layout for the requested region.
	* @note On WebGPU this corresponds to `GPUQueue.writeTexture()` and does not implicitly pad rows to 256 bytes.
	* @note On WebGL, padded CPU data is supported via the same `bytesPerRow` and `rowsPerImage` options.
	*/
	writeData(data, options) {
		throw new Error("readBuffer not implemented");
	}
	/**
	* WebGL can read data synchronously.
	* @note While it is convenient, the performance penalty is very significant
	*/
	readDataSyncWebGL(options) {
		throw new Error("readDataSyncWebGL not available");
	}
	/** Generate mipmaps (WebGL only) */
	generateMipmapsWebGL() {
		throw new Error("generateMipmapsWebGL not available");
	}
	/** Ensure we have integer coordinates */
	static normalizeProps(device, props) {
		const newProps = { ...props };
		const { width, height } = newProps;
		if (typeof width === "number") newProps.width = Math.max(1, Math.ceil(width));
		if (typeof height === "number") newProps.height = Math.max(1, Math.ceil(height));
		return newProps;
	}
	/** Initialize texture with supplied props */
	_initializeData(data) {
		if (this.device.isExternalImage(data)) this.copyExternalImage({
			image: data,
			width: this.width,
			height: this.height,
			depth: this.depth,
			mipLevel: 0,
			x: 0,
			y: 0,
			z: 0,
			aspect: "all",
			colorSpace: "srgb",
			premultipliedAlpha: false,
			flipY: false
		});
		else if (data) this.copyImageData({
			data,
			mipLevel: 0,
			x: 0,
			y: 0,
			z: 0,
			aspect: "all"
		});
	}
	_normalizeCopyImageDataOptions(options_) {
		const { data, depth, ...writeOptions } = options_;
		const options = this._normalizeTextureWriteOptions({
			...writeOptions,
			depthOrArrayLayers: writeOptions.depthOrArrayLayers ?? depth
		});
		return {
			data,
			depth: options.depthOrArrayLayers,
			...options
		};
	}
	_normalizeCopyExternalImageOptions(options_) {
		const optionsWithoutUndefined = Texture._omitUndefined(options_);
		const mipLevel = optionsWithoutUndefined.mipLevel ?? 0;
		const mipLevelSize = this._getMipLevelSize(mipLevel);
		const size = this.device.getExternalImageSize(options_.image);
		const options = {
			...Texture.defaultCopyExternalImageOptions,
			...mipLevelSize,
			...size,
			...optionsWithoutUndefined
		};
		options.width = Math.min(options.width, mipLevelSize.width - options.x);
		options.height = Math.min(options.height, mipLevelSize.height - options.y);
		options.depth = Math.min(options.depth, mipLevelSize.depthOrArrayLayers - options.z);
		return options;
	}
	_normalizeTextureReadOptions(options_) {
		const optionsWithoutUndefined = Texture._omitUndefined(options_);
		const mipLevel = optionsWithoutUndefined.mipLevel ?? 0;
		const mipLevelSize = this._getMipLevelSize(mipLevel);
		const options = {
			...Texture.defaultTextureReadOptions,
			...mipLevelSize,
			...optionsWithoutUndefined
		};
		options.width = Math.min(options.width, mipLevelSize.width - options.x);
		options.height = Math.min(options.height, mipLevelSize.height - options.y);
		options.depthOrArrayLayers = Math.min(options.depthOrArrayLayers, mipLevelSize.depthOrArrayLayers - options.z);
		return options;
	}
	/**
	* Normalizes a texture read request and validates the color-only readback contract used by the
	* current texture read APIs. Supported dimensions are `2d`, `cube`, `cube-array`,
	* `2d-array`, and `3d`.
	*
	* @throws if the texture format, aspect, or dimension is not supported by the first-pass
	* color-read implementation.
	*/
	_getSupportedColorReadOptions(options_) {
		const options = this._normalizeTextureReadOptions(options_);
		const formatInfo = textureFormatDecoder.getInfo(this.format);
		this._validateColorReadAspect(options);
		this._validateColorReadFormat(formatInfo);
		switch (this.dimension) {
			case "2d":
			case "cube":
			case "cube-array":
			case "2d-array":
			case "3d": return options;
			default: throw new Error(`${this} color readback does not support ${this.dimension} textures`);
		}
	}
	/** Validates that a read request targets the full color aspect of the texture. */
	_validateColorReadAspect(options) {
		if (options.aspect !== "all") throw new Error(`${this} color readback only supports aspect 'all'`);
	}
	/** Validates that a read request targets an uncompressed color-renderable texture format. */
	_validateColorReadFormat(formatInfo) {
		if (formatInfo.compressed) throw new Error(`${this} color readback does not support compressed formats (${this.format})`);
		switch (formatInfo.attachment) {
			case "color": return;
			case "depth": throw new Error(`${this} color readback does not support depth formats (${this.format})`);
			case "stencil": throw new Error(`${this} color readback does not support stencil formats (${this.format})`);
			case "depth-stencil": throw new Error(`${this} color readback does not support depth-stencil formats (${this.format})`);
			default: throw new Error(`${this} color readback does not support format ${this.format}`);
		}
	}
	_normalizeTextureWriteOptions(options_) {
		const optionsWithoutUndefined = Texture._omitUndefined(options_);
		const mipLevel = optionsWithoutUndefined.mipLevel ?? 0;
		const mipLevelSize = this._getMipLevelSize(mipLevel);
		const options = {
			...Texture.defaultTextureWriteOptions,
			...mipLevelSize,
			...optionsWithoutUndefined
		};
		options.width = Math.min(options.width, mipLevelSize.width - options.x);
		options.height = Math.min(options.height, mipLevelSize.height - options.y);
		options.depthOrArrayLayers = Math.min(options.depthOrArrayLayers, mipLevelSize.depthOrArrayLayers - options.z);
		const layout = textureFormatDecoder.computeMemoryLayout({
			format: this.format,
			width: options.width,
			height: options.height,
			depth: options.depthOrArrayLayers,
			byteAlignment: this.byteAlignment
		});
		const minimumBytesPerRow = layout.bytesPerPixel * options.width;
		options.bytesPerRow = optionsWithoutUndefined.bytesPerRow ?? layout.bytesPerRow;
		options.rowsPerImage = optionsWithoutUndefined.rowsPerImage ?? options.height;
		if (options.bytesPerRow < minimumBytesPerRow) throw new Error(`bytesPerRow (${options.bytesPerRow}) must be at least ${minimumBytesPerRow} for ${this.format}`);
		if (options.rowsPerImage < options.height) throw new Error(`rowsPerImage (${options.rowsPerImage}) must be at least ${options.height} for ${this.format}`);
		const bytesPerPixel = this.device.getTextureFormatInfo(this.format).bytesPerPixel;
		if (bytesPerPixel && options.bytesPerRow % bytesPerPixel !== 0) throw new Error(`bytesPerRow (${options.bytesPerRow}) must be a multiple of bytesPerPixel (${bytesPerPixel}) for ${this.format}`);
		return options;
	}
	_getMipLevelSize(mipLevel) {
		return {
			width: Math.max(1, this.width >> mipLevel),
			height: this.baseDimension === "1d" ? 1 : Math.max(1, this.height >> mipLevel),
			depthOrArrayLayers: this.dimension === "3d" ? Math.max(1, this.depth >> mipLevel) : this.depth
		};
	}
	getAllocatedByteLength() {
		let allocatedByteLength = 0;
		for (let mipLevel = 0; mipLevel < this.mipLevels; mipLevel++) {
			const { width, height, depthOrArrayLayers } = this._getMipLevelSize(mipLevel);
			allocatedByteLength += textureFormatDecoder.computeMemoryLayout({
				format: this.format,
				width,
				height,
				depth: depthOrArrayLayers,
				byteAlignment: 1
			}).byteLength;
		}
		return allocatedByteLength * this.samples;
	}
	static _omitUndefined(options) {
		return Object.fromEntries(Object.entries(options).filter(([, value]) => value !== void 0));
	}
	static defaultProps = {
		...Resource.defaultProps,
		data: null,
		dimension: "2d",
		format: "rgba8unorm",
		usage: Texture.SAMPLE | Texture.RENDER | Texture.COPY_DST,
		width: void 0,
		height: void 0,
		depth: 1,
		mipLevels: 1,
		samples: void 0,
		sampler: {},
		view: void 0
	};
	static defaultCopyDataOptions = {
		data: void 0,
		byteOffset: 0,
		bytesPerRow: void 0,
		rowsPerImage: void 0,
		width: void 0,
		height: void 0,
		depthOrArrayLayers: void 0,
		depth: 1,
		mipLevel: 0,
		x: 0,
		y: 0,
		z: 0,
		aspect: "all"
	};
	/** Default options */
	static defaultCopyExternalImageOptions = {
		image: void 0,
		sourceX: 0,
		sourceY: 0,
		width: void 0,
		height: void 0,
		depth: 1,
		mipLevel: 0,
		x: 0,
		y: 0,
		z: 0,
		aspect: "all",
		colorSpace: "srgb",
		premultipliedAlpha: false,
		flipY: false
	};
	static defaultTextureReadOptions = {
		x: 0,
		y: 0,
		z: 0,
		width: void 0,
		height: void 0,
		depthOrArrayLayers: 1,
		mipLevel: 0,
		aspect: "all"
	};
	static defaultTextureWriteOptions = {
		byteOffset: 0,
		bytesPerRow: void 0,
		rowsPerImage: void 0,
		x: 0,
		y: 0,
		z: 0,
		width: void 0,
		height: void 0,
		depthOrArrayLayers: 1,
		mipLevel: 0,
		aspect: "all"
	};
};
var color_default = {
	name: "color",
	dependencies: [],
	source: `

@must_use
fn deckgl_premultiplied_alpha(fragColor: vec4<f32>) -> vec4<f32> {
    return vec4(fragColor.rgb * fragColor.a, fragColor.a); 
};
`,
	getUniforms: (_props) => {
		return {};
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/shaderlib/misc/geometry.js
var source$1 = `\
const SMOOTH_EDGE_RADIUS: f32 = 0.5;

struct VertexGeometry {
  position: vec4<f32>,
  worldPosition: vec3<f32>,
  worldPositionAlt: vec3<f32>,
  normal: vec3<f32>,
  uv: vec2<f32>,
  pickingColor: vec3<f32>,
};

var<private> geometry_: VertexGeometry = VertexGeometry(
  vec4<f32>(0.0, 0.0, 1.0, 0.0),
  vec3<f32>(0.0, 0.0, 0.0),
  vec3<f32>(0.0, 0.0, 0.0),
  vec3<f32>(0.0, 0.0, 0.0),
  vec2<f32>(0.0, 0.0),
  vec3<f32>(0.0, 0.0, 0.0)
);

struct FragmentGeometry {
  uv: vec2<f32>,
};

var<private> fragmentGeometry: FragmentGeometry;

fn smoothedge(edge: f32, x: f32) -> f32 {
  return smoothstep(edge - SMOOTH_EDGE_RADIUS, edge + SMOOTH_EDGE_RADIUS, x);
}
`;
var defines = "#define SMOOTH_EDGE_RADIUS 0.5";
var geometry_default = {
	name: "geometry",
	source: source$1,
	vs: `\
${defines}

struct VertexGeometry {
  vec4 position;
  vec3 worldPosition;
  vec3 worldPositionAlt;
  vec3 normal;
  vec2 uv;
  vec3 pickingColor;
} geometry = VertexGeometry(
  vec4(0.0, 0.0, 1.0, 0.0),
  vec3(0.0),
  vec3(0.0),
  vec3(0.0),
  vec2(0.0),
  vec3(0.0)
);
`,
	fs: `\
${defines}

struct FragmentGeometry {
  vec2 uv;
} geometry;

float smoothedge(float edge, float x) {
  return smoothstep(edge - SMOOTH_EDGE_RADIUS, edge + SMOOTH_EDGE_RADIUS, x);
}
`
};
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/input/input-consts.js
var InputEvent;
(function(InputEvent) {
	InputEvent[InputEvent["Start"] = 1] = "Start";
	InputEvent[InputEvent["Move"] = 2] = "Move";
	InputEvent[InputEvent["End"] = 4] = "End";
	InputEvent[InputEvent["Cancel"] = 8] = "Cancel";
})(InputEvent || (InputEvent = {}));
var InputDirection;
(function(InputDirection) {
	InputDirection[InputDirection["None"] = 0] = "None";
	InputDirection[InputDirection["Left"] = 1] = "Left";
	InputDirection[InputDirection["Right"] = 2] = "Right";
	InputDirection[InputDirection["Up"] = 4] = "Up";
	InputDirection[InputDirection["Down"] = 8] = "Down";
	InputDirection[InputDirection["Horizontal"] = 3] = "Horizontal";
	InputDirection[InputDirection["Vertical"] = 12] = "Vertical";
	InputDirection[InputDirection["All"] = 15] = "All";
})(InputDirection || (InputDirection = {}));
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/recognizer/recognizer-state.js
var RecognizerState;
(function(RecognizerState) {
	RecognizerState[RecognizerState["Possible"] = 1] = "Possible";
	RecognizerState[RecognizerState["Began"] = 2] = "Began";
	RecognizerState[RecognizerState["Changed"] = 4] = "Changed";
	RecognizerState[RecognizerState["Ended"] = 8] = "Ended";
	RecognizerState[RecognizerState["Recognized"] = 8] = "Recognized";
	RecognizerState[RecognizerState["Cancelled"] = 16] = "Cancelled";
	RecognizerState[RecognizerState["Failed"] = 32] = "Failed";
})(RecognizerState || (RecognizerState = {}));
var TOUCH_ACTION_AUTO = "auto";
var TOUCH_ACTION_MANIPULATION = "manipulation";
var TOUCH_ACTION_NONE = "none";
var TOUCH_ACTION_PAN_X = "pan-x";
var TOUCH_ACTION_PAN_Y = "pan-y";
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/touchaction/clean-touch-actions.js
/**
* when the touchActions are collected they are not a valid value, so we need to clean things up. *
* @returns valid touchAction
*/
function cleanTouchActions(actions) {
	if (actions.includes("none")) return TOUCH_ACTION_NONE;
	const hasPanX = actions.includes(TOUCH_ACTION_PAN_X);
	const hasPanY = actions.includes(TOUCH_ACTION_PAN_Y);
	if (hasPanX && hasPanY) return TOUCH_ACTION_NONE;
	if (hasPanX || hasPanY) return hasPanX ? TOUCH_ACTION_PAN_X : TOUCH_ACTION_PAN_Y;
	if (actions.includes("manipulation")) return TOUCH_ACTION_MANIPULATION;
	return TOUCH_ACTION_AUTO;
}
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/touchaction/touchaction.js
/**
* Touch Action
* sets the touchAction property or uses the js alternative
*/
var TouchAction = class {
	constructor(manager, value) {
		this.actions = "";
		this.manager = manager;
		this.set(value);
	}
	/**
	* set the touchAction value on the element or enable the polyfill
	*/
	set(value) {
		if (value === "compute") value = this.compute();
		if (this.manager.element) {
			this.manager.element.style.touchAction = value;
			this.actions = value;
		}
	}
	/**
	* just re-set the touchAction value
	*/
	update() {
		this.set(this.manager.options.touchAction);
	}
	/**
	* compute the value for the touchAction property based on the recognizer's settings
	*/
	compute() {
		let actions = [];
		for (const recognizer of this.manager.recognizers) if (recognizer.options.enable) actions = actions.concat(recognizer.getTouchAction());
		return cleanTouchActions(actions.join(" "));
	}
};
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/utils/split-str.js
/**
* split string on whitespace
* @returns {Array} words
*/
function splitStr(str) {
	return str.trim().split(/\s+/g);
}
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/utils/event-listeners.js
/**
* addEventListener with multiple events at once
*/
function addEventListeners(target, types, handler) {
	if (!target) return;
	for (const type of splitStr(types)) target.addEventListener(type, handler, false);
}
/**
* removeEventListener with multiple events at once
*/
function removeEventListeners(target, types, handler) {
	if (!target) return;
	for (const type of splitStr(types)) target.removeEventListener(type, handler, false);
}
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/utils/get-window-for-element.js
/**
* get the window object of an element
*/
function getWindowForElement(element) {
	return (element.ownerDocument || element).defaultView;
}
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/utils/has-parent.js
/**
* find if a node is in the given parent
*/
function hasParent(node, parent) {
	let ancestor = node;
	while (ancestor) {
		if (ancestor === parent) return true;
		ancestor = ancestor.parentNode;
	}
	return false;
}
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/input/get-center.js
/**
* get the center of all the pointers
*/
function getCenter(pointers) {
	const pointersLength = pointers.length;
	if (pointersLength === 1) return {
		x: Math.round(pointers[0].clientX),
		y: Math.round(pointers[0].clientY)
	};
	let x = 0;
	let y = 0;
	let i = 0;
	while (i < pointersLength) {
		x += pointers[i].clientX;
		y += pointers[i].clientY;
		i++;
	}
	return {
		x: Math.round(x / pointersLength),
		y: Math.round(y / pointersLength)
	};
}
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/input/simple-clone-input-data.js
/**
* create a simple clone from the input used for storage of firstInput and firstMultiple
*/
function simpleCloneInputData(input) {
	const pointers = [];
	let i = 0;
	while (i < input.pointers.length) {
		pointers[i] = {
			clientX: Math.round(input.pointers[i].clientX),
			clientY: Math.round(input.pointers[i].clientY)
		};
		i++;
	}
	return {
		timeStamp: Date.now(),
		pointers,
		center: getCenter(pointers),
		deltaX: input.deltaX,
		deltaY: input.deltaY
	};
}
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/input/get-distance.js
/**
* calculate the absolute distance between two points
* @returns distance
*/
function getPointDistance(p1, p2) {
	const x = p2.x - p1.x;
	const y = p2.y - p1.y;
	return Math.sqrt(x * x + y * y);
}
/**
* calculate the absolute distance between two pointer events
* @returns distance
*/
function getEventDistance(p1, p2) {
	const x = p2.clientX - p1.clientX;
	const y = p2.clientY - p1.clientY;
	return Math.sqrt(x * x + y * y);
}
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/input/get-angle.js
/**
* calculate the angle between two coordinates
* @returns angle in degrees
*/
function getPointAngle(p1, p2) {
	const x = p2.x - p1.x;
	const y = p2.y - p1.y;
	return Math.atan2(y, x) * 180 / Math.PI;
}
/**
* calculate the angle between two pointer events
* @returns angle in degrees
*/
function getEventAngle(p1, p2) {
	const x = p2.clientX - p1.clientX;
	const y = p2.clientY - p1.clientY;
	return Math.atan2(y, x) * 180 / Math.PI;
}
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/input/get-direction.js
/**
* get the direction between two points
* @returns direction
*/
function getDirection(dx, dy) {
	if (dx === dy) return InputDirection.None;
	if (Math.abs(dx) >= Math.abs(dy)) return dx < 0 ? InputDirection.Left : InputDirection.Right;
	return dy < 0 ? InputDirection.Up : InputDirection.Down;
}
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/input/get-delta-xy.js
/** Populates input.deltaX, input.deltaY */
function computeDeltaXY(session, input) {
	const center = input.center;
	let offset = session.offsetDelta;
	let prevDelta = session.prevDelta;
	const prevInput = session.prevInput;
	if (input.eventType === InputEvent.Start || prevInput?.eventType === InputEvent.End) {
		prevDelta = session.prevDelta = {
			x: prevInput?.deltaX || 0,
			y: prevInput?.deltaY || 0
		};
		offset = session.offsetDelta = {
			x: center.x,
			y: center.y
		};
	}
	return {
		deltaX: prevDelta.x + (center.x - offset.x),
		deltaY: prevDelta.y + (center.y - offset.y)
	};
}
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/input/get-velocity.js
/**
* calculate the velocity between two points. unit is in px per ms.
*/
function getVelocity(deltaTime, x, y) {
	return {
		x: x / deltaTime || 0,
		y: y / deltaTime || 0
	};
}
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/input/get-scale.js
/**
* calculate the scale factor between two pointersets
* no scale is 1, and goes down to 0 when pinched together, and bigger when pinched out
*/
function getScale(start, end) {
	return getEventDistance(end[0], end[1]) / getEventDistance(start[0], start[1]);
}
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/input/get-rotation.js
/**
* calculate the rotation degrees between two pointer sets
* @returns rotation in degrees
*/
function getRotation(start, end) {
	return getEventAngle(end[1], end[0]) - getEventAngle(start[1], start[0]);
}
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/input/compute-interval-input-data.js
/**
* velocity is calculated every x ms
*/
function computeIntervalInputData(session, input) {
	const last = session.lastInterval || input;
	const deltaTime = input.timeStamp - last.timeStamp;
	let velocity;
	let velocityX;
	let velocityY;
	let direction;
	if (input.eventType !== InputEvent.Cancel && (deltaTime > 25 || last.velocity === void 0)) {
		const deltaX = input.deltaX - last.deltaX;
		const deltaY = input.deltaY - last.deltaY;
		const v = getVelocity(deltaTime, deltaX, deltaY);
		velocityX = v.x;
		velocityY = v.y;
		velocity = Math.abs(v.x) > Math.abs(v.y) ? v.x : v.y;
		direction = getDirection(deltaX, deltaY);
		session.lastInterval = input;
	} else {
		velocity = last.velocity;
		velocityX = last.velocityX;
		velocityY = last.velocityY;
		direction = last.direction;
	}
	input.velocity = velocity;
	input.velocityX = velocityX;
	input.velocityY = velocityY;
	input.direction = direction;
}
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/input/compute-input-data.js
/**
* extend the data with some usable properties like scale, rotate, velocity etc
*/
function computeInputData(manager, input) {
	const { session } = manager;
	const { pointers } = input;
	const { length: pointersLength } = pointers;
	if (!session.firstInput) session.firstInput = simpleCloneInputData(input);
	if (pointersLength > 1 && !session.firstMultiple) session.firstMultiple = simpleCloneInputData(input);
	else if (pointersLength === 1) session.firstMultiple = false;
	const { firstInput, firstMultiple } = session;
	const offsetCenter = firstMultiple ? firstMultiple.center : firstInput.center;
	const center = input.center = getCenter(pointers);
	input.timeStamp = Date.now();
	input.deltaTime = input.timeStamp - firstInput.timeStamp;
	input.angle = getPointAngle(offsetCenter, center);
	input.distance = getPointDistance(offsetCenter, center);
	const { deltaX, deltaY } = computeDeltaXY(session, input);
	input.deltaX = deltaX;
	input.deltaY = deltaY;
	input.offsetDirection = getDirection(input.deltaX, input.deltaY);
	const overallVelocity = getVelocity(input.deltaTime, input.deltaX, input.deltaY);
	input.overallVelocityX = overallVelocity.x;
	input.overallVelocityY = overallVelocity.y;
	input.overallVelocity = Math.abs(overallVelocity.x) > Math.abs(overallVelocity.y) ? overallVelocity.x : overallVelocity.y;
	input.scale = firstMultiple ? getScale(firstMultiple.pointers, pointers) : 1;
	input.rotation = firstMultiple ? getRotation(firstMultiple.pointers, pointers) : 0;
	input.maxPointers = !session.prevInput ? input.pointers.length : input.pointers.length > session.prevInput.maxPointers ? input.pointers.length : session.prevInput.maxPointers;
	let target = manager.element;
	if (hasParent(input.srcEvent.target, target)) target = input.srcEvent.target;
	input.target = target;
	computeIntervalInputData(session, input);
	return input;
}
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/input/input-handler.js
/**
* handle input events
*/
function inputHandler(manager, eventType, input) {
	const pointersLen = input.pointers.length;
	const changedPointersLen = input.changedPointers.length;
	const isFirst = eventType & InputEvent.Start && pointersLen - changedPointersLen === 0;
	const isFinal = eventType & (InputEvent.End | InputEvent.Cancel) && pointersLen - changedPointersLen === 0;
	input.isFirst = Boolean(isFirst);
	input.isFinal = Boolean(isFinal);
	if (isFirst) manager.session = {};
	input.eventType = eventType;
	const processedInput = computeInputData(manager, input);
	manager.emit("hammer.input", processedInput);
	manager.recognize(processedInput);
	manager.session.prevInput = processedInput;
}
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/input/input.js
/**
* create new input type manager
*/
var Input$1 = class {
	constructor(manager) {
		this.evEl = "";
		this.evWin = "";
		this.evTarget = "";
		/** smaller wrapper around the handler, for the scope and the enabled state of the manager,
		* so when disabled the input events are completely bypassed.
		*/
		this.domHandler = (ev) => {
			if (this.manager.options.enable) this.handler(ev);
		};
		this.manager = manager;
		this.element = manager.element;
		this.target = manager.options.inputTarget || manager.element;
	}
	callback(eventType, input) {
		inputHandler(this.manager, eventType, input);
	}
	/**
	* bind the events
	*/
	init() {
		addEventListeners(this.element, this.evEl, this.domHandler);
		addEventListeners(this.target, this.evTarget, this.domHandler);
		addEventListeners(getWindowForElement(this.element), this.evWin, this.domHandler);
	}
	/**
	* unbind the events
	*/
	destroy() {
		removeEventListeners(this.element, this.evEl, this.domHandler);
		removeEventListeners(this.target, this.evTarget, this.domHandler);
		removeEventListeners(getWindowForElement(this.element), this.evWin, this.domHandler);
	}
};
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/inputs/pointerevent.js
var POINTER_INPUT_MAP = {
	pointerdown: InputEvent.Start,
	pointermove: InputEvent.Move,
	pointerup: InputEvent.End,
	pointercancel: InputEvent.Cancel,
	pointerout: InputEvent.Cancel
};
var POINTER_ELEMENT_EVENTS = "pointerdown";
var POINTER_WINDOW_EVENTS = "pointermove pointerup pointercancel";
/**
* Pointer events input
*/
var PointerEventInput = class extends Input$1 {
	constructor(manager) {
		super(manager);
		this.evEl = POINTER_ELEMENT_EVENTS;
		this.evWin = POINTER_WINDOW_EVENTS;
		this.store = this.manager.session.pointerEvents = [];
		this.init();
	}
	/**
	* handle mouse events
	*/
	handler(ev) {
		const { store } = this;
		let removePointer = false;
		const eventType = POINTER_INPUT_MAP[ev.type];
		const pointerType = ev.pointerType;
		const isTouch = pointerType === "touch";
		let storeIndex = store.findIndex((e) => e.pointerId === ev.pointerId);
		if (eventType & InputEvent.Start && (ev.buttons || isTouch)) {
			if (storeIndex < 0) {
				store.push(ev);
				storeIndex = store.length - 1;
			}
		} else if (eventType & (InputEvent.End | InputEvent.Cancel)) removePointer = true;
		if (storeIndex < 0) return;
		store[storeIndex] = ev;
		this.callback(eventType, {
			pointers: store,
			changedPointers: [ev],
			eventType,
			pointerType,
			srcEvent: ev
		});
		if (removePointer) store.splice(storeIndex, 1);
	}
};
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/utils/prefixed.js
var VENDOR_PREFIXES = [
	"",
	"webkit",
	"Moz",
	"MS",
	"ms",
	"o"
];
/**
* get the prefixed property
* @returns prefixed property name
*/
function prefixed(obj, property) {
	const camelProp = property[0].toUpperCase() + property.slice(1);
	for (const prefix of VENDOR_PREFIXES) {
		const prop = prefix ? prefix + camelProp : property;
		if (prop in obj) return prop;
	}
}
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/manager.js
var STOP = 1;
var FORCED_STOP = 2;
var defaultOptions = {
	touchAction: "compute",
	enable: true,
	inputTarget: null,
	cssProps: {
		/**
		* Disables text selection to improve the dragging gesture. Mainly for desktop browsers.
		*/
		userSelect: "none",
		/**
		* (Webkit) Disable default dragging behavior
		*/
		userDrag: "none",
		/**
		* (iOS only) Disables the default callout shown when you touch and hold a touch target.
		* When you touch and hold a touch target such as a link, Safari displays
		* a callout containing information about the link. This property allows you to disable that callout.
		*/
		touchCallout: "none",
		/**
		* (iOS only) Sets the color of the highlight that appears over a link while it's being tapped.
		*/
		tapHighlightColor: "rgba(0,0,0,0)"
	}
};
/**
* Manager
*/
var Manager = class {
	constructor(element, options) {
		this.options = {
			...defaultOptions,
			...options,
			cssProps: {
				...defaultOptions.cssProps,
				...options.cssProps
			},
			inputTarget: options.inputTarget || element
		};
		this.handlers = {};
		this.session = {};
		this.recognizers = [];
		this.oldCssProps = {};
		this.element = element;
		this.input = new PointerEventInput(this);
		this.touchAction = new TouchAction(this, this.options.touchAction);
		this.toggleCssProps(true);
	}
	/**
	* set options
	*/
	set(options) {
		Object.assign(this.options, options);
		if (options.touchAction) this.touchAction.update();
		if (options.inputTarget) {
			this.input.destroy();
			this.input.target = options.inputTarget;
			this.input.init();
		}
		return this;
	}
	/**
	* stop recognizing for this session.
	* This session will be discarded, when a new [input]start event is fired.
	* When forced, the recognizer cycle is stopped immediately.
	*/
	stop(force) {
		this.session.stopped = force ? FORCED_STOP : STOP;
	}
	/**
	* run the recognizers!
	* called by the inputHandler function on every movement of the pointers (touches)
	* it walks through all the recognizers and tries to detect the gesture that is being made
	*/
	recognize(inputData) {
		const { session } = this;
		if (session.stopped) return;
		if (this.session.prevented) inputData.srcEvent.preventDefault();
		let recognizer;
		const { recognizers } = this;
		let { curRecognizer } = session;
		if (!curRecognizer || curRecognizer && curRecognizer.state & RecognizerState.Recognized) curRecognizer = session.curRecognizer = null;
		let i = 0;
		while (i < recognizers.length) {
			recognizer = recognizers[i];
			if (session.stopped !== FORCED_STOP && (!curRecognizer || recognizer === curRecognizer || recognizer.canRecognizeWith(curRecognizer))) recognizer.recognize(inputData);
			else recognizer.reset();
			if (!curRecognizer && recognizer.state & (RecognizerState.Began | RecognizerState.Changed | RecognizerState.Ended)) curRecognizer = session.curRecognizer = recognizer;
			i++;
		}
	}
	/**
	* get a recognizer by its event name.
	*/
	get(recognizerName) {
		const { recognizers } = this;
		for (let i = 0; i < recognizers.length; i++) if (recognizers[i].options.event === recognizerName) return recognizers[i];
		return null;
	}
	/**
	* add a recognizer to the manager
	* existing recognizers with the same event name will be removed
	*/
	add(recognizer) {
		if (Array.isArray(recognizer)) {
			for (const item of recognizer) this.add(item);
			return this;
		}
		const existing = this.get(recognizer.options.event);
		if (existing) this.remove(existing);
		this.recognizers.push(recognizer);
		recognizer.manager = this;
		this.touchAction.update();
		return recognizer;
	}
	/**
	* remove a recognizer by name or instance
	*/
	remove(recognizerOrName) {
		if (Array.isArray(recognizerOrName)) {
			for (const item of recognizerOrName) this.remove(item);
			return this;
		}
		const recognizer = typeof recognizerOrName === "string" ? this.get(recognizerOrName) : recognizerOrName;
		if (recognizer) {
			const { recognizers } = this;
			const index = recognizers.indexOf(recognizer);
			if (index !== -1) {
				recognizers.splice(index, 1);
				this.touchAction.update();
			}
		}
		return this;
	}
	/**
	* bind event
	*/
	on(events, handler) {
		if (!events || !handler) return;
		const { handlers } = this;
		for (const event of splitStr(events)) {
			handlers[event] = handlers[event] || [];
			handlers[event].push(handler);
		}
	}
	/**
	* unbind event, leave hander blank to remove all handlers
	*/
	off(events, handler) {
		if (!events) return;
		const { handlers } = this;
		for (const event of splitStr(events)) if (!handler) delete handlers[event];
		else if (handlers[event]) handlers[event].splice(handlers[event].indexOf(handler), 1);
	}
	/**
	* emit event to the listeners
	*/
	emit(event, data) {
		const handlers = this.handlers[event] && this.handlers[event].slice();
		if (!handlers || !handlers.length) return;
		const evt = data;
		evt.type = event;
		evt.preventDefault = function() {
			data.srcEvent.preventDefault();
		};
		let i = 0;
		while (i < handlers.length) {
			handlers[i](evt);
			i++;
		}
	}
	/**
	* destroy the manager and unbinds all events
	* it doesn't unbind dom events, that is the user own responsibility
	*/
	destroy() {
		this.toggleCssProps(false);
		this.handlers = {};
		this.session = {};
		this.input.destroy();
		this.element = null;
	}
	/**
	* add/remove the css properties as defined in manager.options.cssProps
	*/
	toggleCssProps(add) {
		const { element } = this;
		if (!element) return;
		for (const [name, value] of Object.entries(this.options.cssProps)) {
			const prop = prefixed(element.style, name);
			if (add) {
				this.oldCssProps[prop] = element.style[prop];
				element.style[prop] = value;
			} else element.style[prop] = this.oldCssProps[prop] || "";
		}
		if (!add) this.oldCssProps = {};
	}
};
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/utils/unique-id.js
/**
* get a unique id
*/
var _uniqueId = 1;
function uniqueId() {
	return _uniqueId++;
}
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/recognizer/state-str.js
/**
* get a usable string, used as event postfix
*/
function stateStr(state) {
	if (state & RecognizerState.Cancelled) return "cancel";
	else if (state & RecognizerState.Ended) return "end";
	else if (state & RecognizerState.Changed) return "move";
	else if (state & RecognizerState.Began) return "start";
	return "";
}
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/recognizer/recognizer.js
/**
* Recognizer flow explained; *
* All recognizers have the initial state of POSSIBLE when a input session starts.
* The definition of a input session is from the first input until the last input, with all it's movement in it. *
* Example session for mouse-input: mousedown -> mousemove -> mouseup
*
* On each recognizing cycle (see Manager.recognize) the .recognize() method is executed
* which determines with state it should be.
*
* If the recognizer has the state FAILED, CANCELLED or RECOGNIZED (equals ENDED), it is reset to
* POSSIBLE to give it another change on the next cycle.
*
*               Possible
*                  |
*            +-----+---------------+
*            |                     |
*      +-----+-----+               |
*      |           |               |
*   Failed      Cancelled          |
*                          +-------+------+
*                          |              |
*                      Recognized       Began
*                                         |
*                                      Changed
*                                         |
*                                  Ended/Recognized
*/
/**
* Recognizer
* Every recognizer needs to extend from this class.
*/
var Recognizer = class {
	constructor(options) {
		this.options = options;
		this.id = uniqueId();
		this.state = RecognizerState.Possible;
		this.simultaneous = {};
		this.requireFail = [];
	}
	/**
	* set options
	*/
	set(options) {
		Object.assign(this.options, options);
		this.manager.touchAction.update();
		return this;
	}
	/**
	* recognize simultaneous with an other recognizer.
	*/
	recognizeWith(recognizerOrName) {
		if (Array.isArray(recognizerOrName)) {
			for (const item of recognizerOrName) this.recognizeWith(item);
			return this;
		}
		let otherRecognizer;
		if (typeof recognizerOrName === "string") {
			otherRecognizer = this.manager.get(recognizerOrName);
			if (!otherRecognizer) throw new Error(`Cannot find recognizer ${recognizerOrName}`);
		} else otherRecognizer = recognizerOrName;
		const { simultaneous } = this;
		if (!simultaneous[otherRecognizer.id]) {
			simultaneous[otherRecognizer.id] = otherRecognizer;
			otherRecognizer.recognizeWith(this);
		}
		return this;
	}
	/**
	* drop the simultaneous link. it doesnt remove the link on the other recognizer.
	*/
	dropRecognizeWith(recognizerOrName) {
		if (Array.isArray(recognizerOrName)) {
			for (const item of recognizerOrName) this.dropRecognizeWith(item);
			return this;
		}
		let otherRecognizer;
		if (typeof recognizerOrName === "string") otherRecognizer = this.manager.get(recognizerOrName);
		else otherRecognizer = recognizerOrName;
		if (otherRecognizer) delete this.simultaneous[otherRecognizer.id];
		return this;
	}
	/**
	* recognizer can only run when an other is failing
	*/
	requireFailure(recognizerOrName) {
		if (Array.isArray(recognizerOrName)) {
			for (const item of recognizerOrName) this.requireFailure(item);
			return this;
		}
		let otherRecognizer;
		if (typeof recognizerOrName === "string") {
			otherRecognizer = this.manager.get(recognizerOrName);
			if (!otherRecognizer) throw new Error(`Cannot find recognizer ${recognizerOrName}`);
		} else otherRecognizer = recognizerOrName;
		const { requireFail } = this;
		if (requireFail.indexOf(otherRecognizer) === -1) {
			requireFail.push(otherRecognizer);
			otherRecognizer.requireFailure(this);
		}
		return this;
	}
	/**
	* drop the requireFailure link. it does not remove the link on the other recognizer.
	*/
	dropRequireFailure(recognizerOrName) {
		if (Array.isArray(recognizerOrName)) {
			for (const item of recognizerOrName) this.dropRequireFailure(item);
			return this;
		}
		let otherRecognizer;
		if (typeof recognizerOrName === "string") otherRecognizer = this.manager.get(recognizerOrName);
		else otherRecognizer = recognizerOrName;
		if (otherRecognizer) {
			const index = this.requireFail.indexOf(otherRecognizer);
			if (index > -1) this.requireFail.splice(index, 1);
		}
		return this;
	}
	/**
	* has require failures boolean
	*/
	hasRequireFailures() {
		return Boolean(this.requireFail.find((recognier) => recognier.options.enable));
	}
	/**
	* if the recognizer can recognize simultaneous with an other recognizer
	*/
	canRecognizeWith(otherRecognizer) {
		return Boolean(this.simultaneous[otherRecognizer.id]);
	}
	/**
	* You should use `tryEmit` instead of `emit` directly to check
	* that all the needed recognizers has failed before emitting.
	*/
	emit(input) {
		if (!input) return;
		const { state } = this;
		if (state < RecognizerState.Ended) this.manager.emit(this.options.event + stateStr(state), input);
		this.manager.emit(this.options.event, input);
		if (input.additionalEvent) this.manager.emit(input.additionalEvent, input);
		if (state >= RecognizerState.Ended) this.manager.emit(this.options.event + stateStr(state), input);
	}
	/**
	* Check that all the require failure recognizers has failed,
	* if true, it emits a gesture event,
	* otherwise, setup the state to FAILED.
	*/
	tryEmit(input) {
		if (this.canEmit()) this.emit(input);
		else this.state = RecognizerState.Failed;
	}
	/**
	* can we emit?
	*/
	canEmit() {
		let i = 0;
		while (i < this.requireFail.length) {
			if (!(this.requireFail[i].state & (RecognizerState.Failed | RecognizerState.Possible))) return false;
			i++;
		}
		return true;
	}
	/**
	* update the recognizer
	*/
	recognize(inputData) {
		const inputDataClone = { ...inputData };
		if (!this.options.enable) {
			this.reset();
			this.state = RecognizerState.Failed;
			return;
		}
		if (this.state & (RecognizerState.Recognized | RecognizerState.Cancelled | RecognizerState.Failed)) this.state = RecognizerState.Possible;
		this.state = this.process(inputDataClone);
		if (this.state & (RecognizerState.Began | RecognizerState.Changed | RecognizerState.Ended | RecognizerState.Cancelled)) this.tryEmit(inputDataClone);
	}
	/**
	* return the event names that are emitted by this recognizer
	*/
	getEventNames() {
		return [this.options.event];
	}
	/**
	* called when the gesture isn't allowed to recognize
	* like when another is being recognized or it is disabled
	*/
	reset() {}
};
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/recognizers/attribute.js
/**
* This recognizer is just used as a base for the simple attribute recognizers.
*/
var AttrRecognizer = class extends Recognizer {
	/**
	* Used to check if it the recognizer receives valid input, like input.distance > 10.
	*/
	attrTest(input) {
		const optionPointers = this.options.pointers;
		return optionPointers === 0 || input.pointers.length === optionPointers;
	}
	/**
	* Process the input and return the state for the recognizer
	*/
	process(input) {
		const { state } = this;
		const { eventType } = input;
		const isRecognized = state & (RecognizerState.Began | RecognizerState.Changed);
		const isValid = this.attrTest(input);
		if (isRecognized && (eventType & InputEvent.Cancel || !isValid)) return state | RecognizerState.Cancelled;
		else if (isRecognized || isValid) {
			if (eventType & InputEvent.End) return state | RecognizerState.Ended;
			else if (!(state & RecognizerState.Began)) return RecognizerState.Began;
			return state | RecognizerState.Changed;
		}
		return RecognizerState.Failed;
	}
};
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/recognizers/tap.js
/**
* A tap is recognized when the pointer is doing a small tap/click. Multiple taps are recognized if they occur
* between the given interval and position. The delay option can be used to recognize multi-taps without firing
* a single tap.
*
* The eventData from the emitted event contains the property `tapCount`, which contains the amount of
* multi-taps being recognized.
*/
var TapRecognizer = class extends Recognizer {
	constructor(options = {}) {
		super({
			enable: true,
			event: "tap",
			pointers: 1,
			taps: 1,
			interval: 300,
			time: 250,
			threshold: 9,
			posThreshold: 10,
			...options
		});
		/** previous time for tap counting */
		this.pTime = null;
		/** previous center for tap counting */
		this.pCenter = null;
		this._timer = null;
		this._input = null;
		this.count = 0;
	}
	getTouchAction() {
		return [TOUCH_ACTION_MANIPULATION];
	}
	process(input) {
		const { options } = this;
		const validPointers = input.pointers.length === options.pointers;
		const validMovement = input.distance < options.threshold;
		const validTouchTime = input.deltaTime < options.time;
		this.reset();
		if (input.eventType & InputEvent.Start && this.count === 0) return this.failTimeout();
		if (validMovement && validTouchTime && validPointers) {
			if (input.eventType !== InputEvent.End) return this.failTimeout();
			const validInterval = this.pTime ? input.timeStamp - this.pTime < options.interval : true;
			const validMultiTap = !this.pCenter || getPointDistance(this.pCenter, input.center) < options.posThreshold;
			this.pTime = input.timeStamp;
			this.pCenter = input.center;
			if (!validMultiTap || !validInterval) this.count = 1;
			else this.count += 1;
			this._input = input;
			if (this.count % options.taps === 0) {
				if (!this.hasRequireFailures()) return RecognizerState.Recognized;
				this._timer = setTimeout(() => {
					this.state = RecognizerState.Recognized;
					this.tryEmit(this._input);
				}, options.interval);
				return RecognizerState.Began;
			}
		}
		return RecognizerState.Failed;
	}
	failTimeout() {
		this._timer = setTimeout(() => {
			this.state = RecognizerState.Failed;
		}, this.options.interval);
		return RecognizerState.Failed;
	}
	reset() {
		clearTimeout(this._timer);
	}
	emit(input) {
		if (this.state === RecognizerState.Recognized) {
			input.tapCount = this.count;
			this.manager.emit(this.options.event, input);
		}
	}
};
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/recognizers/trackpad.js
var TrackpadRecognizer = class extends AttrRecognizer {
	constructor() {
		super(...arguments);
		this.wheelSession = null;
		this.wheelSessionUnsubscribe = null;
		this.handleWheelSessionEvent = (event) => {
			if (event.device === "trackpad") this.handleTrackpadEvent(event);
		};
	}
	set(options) {
		const { wheelSession, ...recognizerOptions } = options;
		if (wheelSession && wheelSession !== this.wheelSession) {
			this.wheelSessionUnsubscribe?.();
			this.wheelSessionUnsubscribe = null;
			this.wheelSession = wheelSession;
		}
		super.set(recognizerOptions);
		this.updateWheelSessionSubscription();
		return this;
	}
	getTrackpadInput(event, overrides = {}) {
		const { srcEvent } = event;
		const deltaX = overrides.deltaX ?? event.deltaX;
		const deltaY = overrides.deltaY ?? event.deltaY;
		const direction = getDirection(deltaX, deltaY);
		const pointer = srcEvent;
		return {
			pointers: [pointer, pointer],
			changedPointers: [pointer, pointer],
			pointerType: "trackpad",
			srcEvent: pointer,
			eventType: event.eventType,
			timeStamp: event.timeStamp,
			deltaTime: event.deltaTime,
			center: event.center,
			deltaX,
			deltaY,
			angle: Math.atan2(deltaY, deltaX) * 180 / Math.PI,
			distance: Math.sqrt(deltaX * deltaX + deltaY * deltaY),
			scale: 1,
			rotation: 0,
			direction,
			offsetDirection: direction,
			velocity: event.velocity,
			velocityX: event.velocityX,
			velocityY: event.velocityY,
			overallVelocity: event.overallVelocity,
			overallVelocityX: event.overallVelocityX,
			overallVelocityY: event.overallVelocityY,
			maxPointers: 2,
			target: srcEvent.target || this.manager.element,
			additionalEvent: "",
			...overrides
		};
	}
	updateWheelSessionSubscription() {
		const shouldSubscribe = Boolean(this.wheelSession && this.options.enable && this.options.trackpad && this.options.pointers === 2);
		if (shouldSubscribe && !this.wheelSessionUnsubscribe) this.wheelSessionUnsubscribe = this.wheelSession.on(this.handleWheelSessionEvent);
		else if (!shouldSubscribe && this.wheelSessionUnsubscribe) {
			this.wheelSessionUnsubscribe();
			this.wheelSessionUnsubscribe = null;
		}
	}
};
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/recognizers/pan.js
var EVENT_NAMES$1 = [
	"",
	"start",
	"move",
	"end",
	"cancel",
	"up",
	"down",
	"left",
	"right"
];
/**
* Pan
* Recognized when the pointer is down and moved in the allowed direction.
*/
var PanRecognizer = class extends TrackpadRecognizer {
	constructor(options = {}) {
		super({
			enable: true,
			pointers: 1,
			event: "pan",
			threshold: 10,
			direction: InputDirection.All,
			trackpad: false,
			...options
		});
		this.trackpadGesture = false;
		this.pX = null;
		this.pY = null;
	}
	getTouchAction() {
		const { options: { direction } } = this;
		const actions = [];
		if (direction & InputDirection.Horizontal) actions.push(TOUCH_ACTION_PAN_Y);
		if (direction & InputDirection.Vertical) actions.push(TOUCH_ACTION_PAN_X);
		return actions;
	}
	getEventNames() {
		return EVENT_NAMES$1.map((suffix) => this.options.event + suffix);
	}
	directionTest(input) {
		const { options } = this;
		let hasMoved = true;
		let { distance } = input;
		let { direction } = input;
		const x = input.deltaX;
		const y = input.deltaY;
		if (!(direction & options.direction)) if (options.direction & InputDirection.Horizontal) {
			direction = x === 0 ? InputDirection.None : x < 0 ? InputDirection.Left : InputDirection.Right;
			hasMoved = x !== this.pX;
			distance = Math.abs(input.deltaX);
		} else {
			direction = y === 0 ? InputDirection.None : y < 0 ? InputDirection.Up : InputDirection.Down;
			hasMoved = y !== this.pY;
			distance = Math.abs(input.deltaY);
		}
		input.direction = direction;
		return hasMoved && distance > options.threshold && Boolean(direction & options.direction);
	}
	attrTest(input) {
		return super.attrTest(input) && (Boolean(this.state & RecognizerState.Began) || !(this.state & RecognizerState.Began) && this.directionTest(input));
	}
	emit(input) {
		this.pX = input.deltaX;
		this.pY = input.deltaY;
		const direction = InputDirection[input.direction].toLowerCase();
		if (direction) input.additionalEvent = this.options.event + direction;
		super.emit(input);
	}
	handleTrackpadEvent(event) {
		if (event.isFirst) this.trackpadGesture = !event.srcEvent.ctrlKey;
		if (!this.trackpadGesture) return;
		this.recognize(this.getTrackpadInput(event, {
			deltaX: -event.deltaX,
			deltaY: -event.deltaY,
			velocity: -event.velocity,
			velocityX: -event.velocityX,
			velocityY: -event.velocityY,
			overallVelocity: -event.overallVelocity,
			overallVelocityX: -event.overallVelocityX,
			overallVelocityY: -event.overallVelocityY
		}));
		if (event.isFinal) this.trackpadGesture = false;
	}
};
//#endregion
//#region node_modules/mjolnir.js/dist/hammerjs/recognizers/pinch.js
var EVENT_NAMES = [
	"",
	"start",
	"move",
	"end",
	"cancel",
	"in",
	"out"
];
/**
* Pinch
* Recognized when two or more pointers are moving toward (zoom-in) or away from each other (zoom-out).
*/
var PinchRecognizer = class extends TrackpadRecognizer {
	constructor(options = {}) {
		super({
			enable: true,
			event: "pinch",
			threshold: 0,
			pointers: 2,
			trackpad: false,
			...options
		});
		this.trackpadGesture = false;
	}
	getTouchAction() {
		return [TOUCH_ACTION_NONE];
	}
	getEventNames() {
		return EVENT_NAMES.map((suffix) => this.options.event + suffix);
	}
	attrTest(input) {
		return super.attrTest(input) && (Math.abs(input.scale - 1) > this.options.threshold || Boolean(this.state & RecognizerState.Began));
	}
	emit(input) {
		if (input.scale !== 1) {
			const inOut = input.scale < 1 ? "in" : "out";
			input.additionalEvent = this.options.event + inOut;
		}
		super.emit(input);
	}
	handleTrackpadEvent(event) {
		if (event.isFirst) this.trackpadGesture = event.srcEvent.ctrlKey;
		if (!this.trackpadGesture) return;
		this.recognize(this.getTrackpadInput(event, {
			deltaX: 0,
			deltaY: 0,
			velocity: 0,
			velocityX: 0,
			velocityY: 0,
			overallVelocity: 0,
			overallVelocityX: 0,
			overallVelocityY: 0,
			scale: Math.exp(-event.deltaY / 100)
		}));
		if (event.isFinal) this.trackpadGesture = false;
	}
};
//#endregion
//#region node_modules/mjolnir.js/dist/inputs/input.js
var Input = class {
	constructor(element, callback, options) {
		this.element = element;
		this.callback = callback;
		this.options = options;
	}
	listen(eventType, enabled) {
		if (enabled) this.element.addEventListener(eventType, this.handleEvent, { passive: false });
		else this.element.removeEventListener(eventType, this.handleEvent);
	}
};
//#endregion
//#region node_modules/mjolnir.js/dist/inputs/wheel-input.js
var firefox = (typeof navigator !== "undefined" && navigator.userAgent ? navigator.userAgent.toLowerCase() : "").indexOf("firefox") !== -1;
var WHEEL_DELTA_PER_LINE$1 = 40;
var SHIFT_MULTIPLIER = .25;
var WheelInput = class extends Input {
	constructor(element, callback, options) {
		options.enable = options.enable ?? false;
		super(element, callback, options);
		this.handleEvent = (event) => {
			if (!this.options.enable) return;
			let value = event.deltaY;
			if (globalThis.WheelEvent) {
				if (firefox && event.deltaMode === globalThis.WheelEvent.DOM_DELTA_PIXEL) value /= globalThis.devicePixelRatio;
				if (event.deltaMode === globalThis.WheelEvent.DOM_DELTA_LINE) value *= WHEEL_DELTA_PER_LINE$1;
			}
			if (event.shiftKey && value) value = value * SHIFT_MULTIPLIER;
			this.callback({
				type: "wheel",
				center: {
					x: event.clientX,
					y: event.clientY
				},
				delta: -value,
				device: this.options.wheelSession?.device ?? "unknown",
				srcEvent: event,
				pointerType: "mouse",
				target: event.target
			});
		};
		if (options.enable) {
			this.wheelSessionUnsubscribe = this.options.wheelSession?.on(() => {});
			this.listen("wheel", true);
		}
	}
	destroy() {
		this.listen("wheel", false);
		this.wheelSessionUnsubscribe?.();
		this.wheelSessionUnsubscribe = void 0;
	}
	/**
	* Enable this input (begin processing events)
	* if the specified event type is among those handled by this input.
	*/
	enableEventType(eventType, enabled) {
		if (eventType === "wheel" && this.options.enable !== enabled) {
			this.options.enable = enabled;
			if (enabled && !this.wheelSessionUnsubscribe) this.wheelSessionUnsubscribe = this.options.wheelSession?.on(() => {});
			this.listen("wheel", enabled);
			if (!enabled) {
				this.wheelSessionUnsubscribe?.();
				this.wheelSessionUnsubscribe = void 0;
			}
		}
	}
};
//#endregion
//#region node_modules/mjolnir.js/dist/inputs/wheel-gesture-session.js
var WHEEL_DELTA_MAGIC_SCALER = 4.000244140625;
var WHEEL_DELTA_PER_LINE = 40;
var DOM_DELTA_PIXEL = 0;
var DOM_DELTA_LINE = 1;
var RAPID_EVENT_INTERVAL = 40;
var SMALL_DELTA_THRESHOLD = 40;
var LEGACY_WHEEL_DELTA_STEP = 120;
var DEFAULT_OPTIONS$1 = {
	classificationDelay: 32,
	endDelay: 80
};
/**
* Groups DOM wheel events into sessions and classifies each session as mouse
* or trackpad input.
*
* The class passively observes wheel events on the target element.
* Classification and timers are dormant while there are no subscribers.
*/
var WheelGestureSession = class {
	constructor(element, options = {}) {
		this.subscriptions = /* @__PURE__ */ new Map();
		this.session = null;
		this.classificationTimer = null;
		this.endTimer = null;
		this.pressedControlKeys = /* @__PURE__ */ new Set();
		this.listeningForControlKeys = false;
		/**
		* Processes one DOM wheel event and returns the classification known at the
		* end of this call. Ambiguous initial events return "unknown".
		*/
		this.handleEvent = (event) => {
			if (!this.hasSubscribers) return "unknown";
			const sample = createSample(event, this.pressedControlKeys.size > 0);
			let session = this.session;
			if (session && sample.timeStamp - session.lastTimeStamp >= this.options.endDelay) {
				this.end();
				if (!this.hasSubscribers) return "unknown";
				session = null;
			}
			if (session) {
				this.scheduleEnd();
				this.addSample(session, sample);
			} else {
				session = this.startPendingSession(sample);
				this.scheduleEnd();
			}
			let { device } = session;
			if (device === "unknown") {
				device = classifyWheelSession(session.samples, false);
				if (device !== "unknown") this.begin(session, device);
			}
			return device;
		};
		this.finishClassification = () => {
			this.classificationTimer = null;
			if (!this.session || this.session.device !== "unknown") return;
			const session = this.session;
			const device = classifyWheelSession(session.samples, true);
			this.begin(session, device === "unknown" ? "mouse" : device);
		};
		this.end = () => {
			if (!this.session) return;
			if (this.session.device === "unknown") {
				const session = this.session;
				const device = classifyWheelSession(session.samples, true);
				this.begin(session, device === "unknown" ? "mouse" : device);
			}
			if (!this.session) return;
			const session = this.session;
			this.emit(InputEvent.End, session.lastEvent);
			this.reset();
		};
		this.handleKeyDown = (event) => {
			if (event.key === "Control") this.pressedControlKeys.add(event.code || event.key);
		};
		this.handleKeyUp = (event) => {
			if (event.key === "Control") if (event.code) this.pressedControlKeys.delete(event.code);
			else this.pressedControlKeys.clear();
		};
		this.handleWindowBlur = () => {
			this.pressedControlKeys.clear();
		};
		this.element = element;
		this.options = {
			...DEFAULT_OPTIONS$1,
			...options
		};
		this.element?.addEventListener("wheel", this.handleEvent, { passive: true });
	}
	get hasSubscribers() {
		return this.subscriptions.size > 0;
	}
	get device() {
		return this.session?.device ?? "unknown";
	}
	on(listener) {
		const subscription = { listener };
		this.subscriptions.set(listener, subscription);
		this.updateControlKeyEventListeners();
		return () => {
			if (this.subscriptions.get(listener) === subscription) this.off(listener);
		};
	}
	off(listener) {
		this.subscriptions.delete(listener);
		this.updateControlKeyEventListeners();
		if (!this.hasSubscribers) this.reset();
	}
	/**
	* Cancels a recognized session. An unclassified pending session is silently
	* discarded.
	*/
	cancel() {
		const session = this.session;
		if (session && session.device !== "unknown") this.emit(InputEvent.Cancel, session.lastEvent);
		this.reset();
	}
	destroy() {
		this.cancel();
		this.subscriptions.clear();
		this.updateControlKeyEventListeners();
		this.element?.removeEventListener("wheel", this.handleEvent);
	}
	startPendingSession(sample) {
		const session = {
			samples: [sample],
			device: "unknown",
			firstTimeStamp: sample.timeStamp,
			lastTimeStamp: sample.timeStamp,
			totalDeltaX: sample.deltaX,
			totalDeltaY: sample.deltaY,
			velocityX: 0,
			velocityY: 0,
			lastEvent: sample.event
		};
		this.session = session;
		this.classificationTimer = globalThis.setTimeout(this.finishClassification, this.options.classificationDelay);
		return session;
	}
	addSample(session, sample) {
		session.samples.push(sample);
		session.lastTimeStamp = sample.timeStamp;
		session.lastEvent = sample.event;
		session.totalDeltaX += sample.deltaX;
		session.totalDeltaY += sample.deltaY;
		if (session.device !== "unknown") {
			const previousSample = session.samples[session.samples.length - 2];
			const elapsed = sample.timeStamp - previousSample.timeStamp;
			session.velocityX = elapsed > 0 ? sample.deltaX / elapsed : 0;
			session.velocityY = elapsed > 0 ? sample.deltaY / elapsed : 0;
			this.emit(InputEvent.Move, sample.event, {
				velocityX: session.velocityX,
				velocityY: session.velocityY
			});
		}
	}
	begin(session, device) {
		session.device = device;
		this.clearClassificationTimer();
		this.emit(InputEvent.Start, session.samples[0].event);
		const elapsed = session.lastTimeStamp - session.firstTimeStamp;
		session.velocityX = elapsed > 0 ? session.totalDeltaX / elapsed : 0;
		session.velocityY = elapsed > 0 ? session.totalDeltaY / elapsed : 0;
		this.emit(InputEvent.Move, session.lastEvent, {
			velocityX: session.velocityX,
			velocityY: session.velocityY
		});
	}
	scheduleEnd() {
		this.clearEndTimer();
		this.endTimer = globalThis.setTimeout(this.end, this.options.endDelay);
	}
	emit(eventType, srcEvent, velocities) {
		const session = this.session;
		if (!session || session.device === "unknown") return;
		const isFirst = eventType === InputEvent.Start;
		const isFinal = eventType === InputEvent.End || eventType === InputEvent.Cancel;
		const timeStamp = isFirst ? session.firstTimeStamp : session.lastTimeStamp;
		const deltaTime = isFirst ? 0 : Math.max(0, timeStamp - session.firstTimeStamp);
		const deltaX = isFirst ? 0 : session.totalDeltaX;
		const deltaY = isFirst ? 0 : session.totalDeltaY;
		const overallVelocityX = deltaTime > 0 ? deltaX / deltaTime : 0;
		const overallVelocityY = deltaTime > 0 ? deltaY / deltaTime : 0;
		const velocityX = isFirst ? 0 : velocities?.velocityX ?? session.velocityX;
		const velocityY = isFirst ? 0 : velocities?.velocityY ?? session.velocityY;
		const event = {
			eventType,
			device: session.device,
			srcEvent,
			timeStamp,
			center: {
				x: srcEvent.clientX,
				y: srcEvent.clientY
			},
			deltaX,
			deltaY,
			deltaTime,
			velocity: Math.abs(velocityX) > Math.abs(velocityY) ? velocityX : velocityY,
			velocityX,
			velocityY,
			overallVelocity: Math.abs(overallVelocityX) > Math.abs(overallVelocityY) ? overallVelocityX : overallVelocityY,
			overallVelocityX,
			overallVelocityY,
			isFirst,
			isFinal
		};
		for (const { listener } of [...this.subscriptions.values()]) listener(event);
	}
	reset() {
		this.clearClassificationTimer();
		this.clearEndTimer();
		this.session = null;
	}
	clearClassificationTimer() {
		if (this.classificationTimer !== null) {
			globalThis.clearTimeout(this.classificationTimer);
			this.classificationTimer = null;
		}
	}
	clearEndTimer() {
		if (this.endTimer !== null) {
			globalThis.clearTimeout(this.endTimer);
			this.endTimer = null;
		}
	}
	updateControlKeyEventListeners() {
		const shouldListen = this.hasSubscribers;
		const eventTarget = getWindow();
		if (!eventTarget || shouldListen === this.listeningForControlKeys) return;
		this.listeningForControlKeys = shouldListen;
		if (shouldListen) {
			eventTarget.addEventListener("keydown", this.handleKeyDown, true);
			eventTarget.addEventListener("keyup", this.handleKeyUp, true);
			eventTarget.addEventListener("blur", this.handleWindowBlur);
		} else {
			eventTarget.removeEventListener("keydown", this.handleKeyDown, true);
			eventTarget.removeEventListener("keyup", this.handleKeyUp, true);
			eventTarget.removeEventListener("blur", this.handleWindowBlur);
			this.pressedControlKeys.clear();
		}
	}
};
function getWindow() {
	if (typeof window !== "undefined") return window;
	return globalThis.document?.defaultView;
}
function createSample(event, isControlKeyDown) {
	let deltaX = event.deltaX;
	let deltaY = event.deltaY;
	if (event.deltaMode === DOM_DELTA_LINE) {
		deltaX *= WHEEL_DELTA_PER_LINE;
		deltaY *= WHEEL_DELTA_PER_LINE;
	}
	return {
		event,
		timeStamp: event.timeStamp,
		deltaX,
		deltaY,
		isControlKeyDown
	};
}
function classifyWheelSession(samples, force) {
	if (samples.some(({ event, isControlKeyDown }) => event.ctrlKey && !isControlKeyDown)) return "trackpad";
	if (samples.some(({ event }) => event.deltaMode !== DOM_DELTA_PIXEL)) return "mouse";
	if (samples.some(isLegacyMouseWheelSample)) return "mouse";
	if (samples.every(({ event }) => {
		const wheelDelta = event.wheelDelta;
		return wheelDelta !== void 0 && Math.abs(wheelDelta) % 40 === 0;
	})) return "mouse";
	if (samples.some(({ deltaX }) => deltaX !== 0)) return "trackpad";
	if (samples.length > 1 && isRapidSmallDeltaSequence(samples)) return "trackpad";
	return force ? "mouse" : "unknown";
}
function isLegacyMouseWheelSample({ event, deltaX, deltaY }) {
	if (deltaX !== 0 || deltaY === 0) return false;
	const magicScaledDelta = Math.abs(deltaY / WHEEL_DELTA_MAGIC_SCALER);
	if (Number.isInteger(magicScaledDelta)) return true;
	const legacyWheelDelta = event.wheelDelta;
	return typeof legacyWheelDelta === "number" && legacyWheelDelta !== 0 && legacyWheelDelta % LEGACY_WHEEL_DELTA_STEP === 0;
}
function isRapidSmallDeltaSequence(samples) {
	for (let index = 0; index < samples.length; index++) {
		const sample = samples[index];
		if (Math.abs(sample.deltaX) > SMALL_DELTA_THRESHOLD || Math.abs(sample.deltaY) > SMALL_DELTA_THRESHOLD) return false;
		if (index > 0 && sample.timeStamp - samples[index - 1].timeStamp > RAPID_EVENT_INTERVAL) return false;
	}
	return true;
}
//#endregion
//#region node_modules/mjolnir.js/dist/inputs/move-input.js
var MOUSE_EVENTS$1 = [
	"mousedown",
	"mousemove",
	"mouseup",
	"mouseover",
	"mouseout",
	"mouseenter",
	"mouseleave"
];
/**
* Hammer.js swallows 'move' events (for pointer/touch/mouse)
* when the pointer is not down. This class sets up a handler
* specifically for these events to work around this limitation.
* Note that this could be extended to more intelligently handle
* move events across input types, e.g. storing multiple simultaneous
* pointer/touch events, calculating speed/direction, etc.
*/
var MoveInput = class extends Input {
	constructor(element, callback, options) {
		super(element, callback, {
			enable: true,
			...options
		});
		this.handleEvent = (event) => {
			this.handleOverEvent(event);
			this.handleOutEvent(event);
			this.handleEnterEvent(event);
			this.handleLeaveEvent(event);
			this.handleMoveEvent(event);
		};
		this.pressed = false;
		const { enable = false } = this.options;
		this.enableMoveEvent = enable;
		this.enableLeaveEvent = enable;
		this.enableEnterEvent = enable;
		this.enableOutEvent = enable;
		this.enableOverEvent = enable;
		if (enable) MOUSE_EVENTS$1.forEach((event) => this.listen(event, true));
	}
	destroy() {
		MOUSE_EVENTS$1.forEach((event) => this.listen(event, false));
	}
	/**
	* Enable this input (begin processing events)
	* if the specified event type is among those handled by this input.
	*/
	enableEventType(eventType, enabled) {
		switch (eventType) {
			case "pointermove":
				if (this.enableMoveEvent !== enabled) {
					this.enableMoveEvent = enabled;
					this.listen("mousedown", enabled);
					this.listen("mousemove", enabled);
					this.listen("mouseup", enabled);
				}
				break;
			case "pointerover":
				if (this.enableOverEvent !== enabled) {
					this.enableOverEvent = enabled;
					this.listen("mouseover", enabled);
				}
				break;
			case "pointerout":
				if (this.enableOutEvent !== enabled) {
					this.enableOutEvent = enabled;
					this.listen("mouseout", enabled);
				}
				break;
			case "pointerenter":
				if (this.enableEnterEvent !== enabled) {
					this.enableEnterEvent = enabled;
					this.listen("mouseenter", enabled);
				}
				break;
			case "pointerleave":
				if (this.enableLeaveEvent !== enabled) {
					this.enableLeaveEvent = enabled;
					this.listen("mouseleave", enabled);
				}
				break;
			default:
		}
	}
	handleOverEvent(event) {
		if (this.enableOverEvent && event.type === "mouseover") this._emit("pointerover", event);
	}
	handleOutEvent(event) {
		if (this.enableOutEvent && event.type === "mouseout") this._emit("pointerout", event);
	}
	handleEnterEvent(event) {
		if (this.enableEnterEvent && event.type === "mouseenter") this._emit("pointerenter", event);
	}
	handleLeaveEvent(event) {
		if (this.enableLeaveEvent && event.type === "mouseleave") this._emit("pointerleave", event);
	}
	handleMoveEvent(event) {
		if (this.enableMoveEvent) switch (event.type) {
			case "mousedown":
				if (event.button >= 0) this.pressed = true;
				break;
			case "mousemove":
				if (event.buttons === 0) this.pressed = false;
				if (!this.pressed) this._emit("pointermove", event);
				break;
			case "mouseup":
				this.pressed = false;
				break;
			default:
		}
	}
	_emit(type, event) {
		this.callback({
			type,
			center: {
				x: event.clientX,
				y: event.clientY
			},
			srcEvent: event,
			pointerType: "mouse",
			target: event.target
		});
	}
};
//#endregion
//#region node_modules/mjolnir.js/dist/inputs/key-input.js
var KEY_EVENTS = ["keydown", "keyup"];
var KeyInput = class extends Input {
	constructor(element, callback, options) {
		super(element, callback, {
			enable: true,
			tabIndex: 0,
			...options
		});
		this.handleEvent = (event) => {
			const targetElement = event.target || event.srcElement;
			if (targetElement.tagName === "INPUT" && targetElement.type === "text" || targetElement.tagName === "TEXTAREA") return;
			if (this.enableDownEvent && event.type === "keydown") this.callback({
				type: "keydown",
				srcEvent: event,
				key: event.key,
				target: event.target
			});
			if (this.enableUpEvent && event.type === "keyup") this.callback({
				type: "keyup",
				srcEvent: event,
				key: event.key,
				target: event.target
			});
		};
		const { enable = false } = this.options;
		this.enableDownEvent = enable;
		this.enableUpEvent = enable;
		element.tabIndex = this.options.tabIndex;
		element.style.outline = "none";
		if (enable) KEY_EVENTS.forEach((event) => this.listen(event, true));
	}
	destroy() {
		KEY_EVENTS.forEach((event) => this.listen(event, false));
	}
	/**
	* Enable this input (begin processing events)
	* if the specified event type is among those handled by this input.
	*/
	enableEventType(eventType, enabled) {
		if (eventType === "keydown" && this.enableDownEvent !== enabled) {
			this.enableDownEvent = enabled;
			this.listen(eventType, enabled);
		}
		if (eventType === "keyup" && this.enableUpEvent !== enabled) {
			this.enableUpEvent = enabled;
			this.listen(eventType, enabled);
		}
	}
};
//#endregion
//#region node_modules/mjolnir.js/dist/inputs/contextmenu-input.js
var ContextmenuInput = class extends Input {
	constructor(element, callback, options) {
		options.enable = options.enable ?? false;
		super(element, callback, options);
		this.handleEvent = (event) => {
			if (!this.options.enable) return;
			this.callback({
				type: "contextmenu",
				center: {
					x: event.clientX,
					y: event.clientY
				},
				srcEvent: event,
				pointerType: "mouse",
				target: event.target
			});
		};
		if (options.enable) this.listen("contextmenu", true);
	}
	destroy() {
		this.listen("contextmenu", false);
	}
	/**
	* Enable this input (begin processing events)
	* if the specified event type is among those handled by this input.
	*/
	enableEventType(eventType, enabled) {
		if (eventType === "contextmenu" && this.options.enable !== enabled) {
			this.options.enable = enabled;
			this.listen("contextmenu", enabled);
		}
	}
};
//#endregion
//#region node_modules/mjolnir.js/dist/utils/event-utils.js
var DOWN_EVENT = 1;
var MOVE_EVENT = 2;
var UP_EVENT = 4;
var MOUSE_EVENTS = {
	pointerdown: DOWN_EVENT,
	pointermove: MOVE_EVENT,
	pointerup: UP_EVENT,
	mousedown: DOWN_EVENT,
	mousemove: MOVE_EVENT,
	mouseup: UP_EVENT
};
var MOUSE_EVENT_BUTTON_LEFT = 0;
var MOUSE_EVENT_BUTTON_MIDDLE = 1;
var MOUSE_EVENT_BUTTON_RIGHT = 2;
var MOUSE_EVENT_BUTTONS_LEFT_MASK = 1;
var MOUSE_EVENT_BUTTONS_RIGHT_MASK = 2;
var MOUSE_EVENT_BUTTONS_MIDDLE_MASK = 4;
/**
* Extract the involved mouse button
*/
function whichButtons(event) {
	const eventType = MOUSE_EVENTS[event.srcEvent.type];
	if (!eventType) return null;
	const { buttons, button } = event.srcEvent;
	let leftButton = false;
	let middleButton = false;
	let rightButton = false;
	if (eventType === MOVE_EVENT) {
		leftButton = Boolean(buttons & MOUSE_EVENT_BUTTONS_LEFT_MASK);
		middleButton = Boolean(buttons & MOUSE_EVENT_BUTTONS_MIDDLE_MASK);
		rightButton = Boolean(buttons & MOUSE_EVENT_BUTTONS_RIGHT_MASK);
	} else {
		leftButton = button === MOUSE_EVENT_BUTTON_LEFT;
		middleButton = button === MOUSE_EVENT_BUTTON_MIDDLE;
		rightButton = button === MOUSE_EVENT_BUTTON_RIGHT;
	}
	return {
		leftButton,
		middleButton,
		rightButton
	};
}
/**
* Calculate event position relative to the root element
*/
function getOffsetPosition(event, rootElement) {
	const center = event.center;
	if (!center) return null;
	const rect = rootElement.getBoundingClientRect();
	const scaleX = rect.width / rootElement.offsetWidth || 1;
	const scaleY = rect.height / rootElement.offsetHeight || 1;
	return {
		center,
		offsetCenter: {
			x: (center.x - rect.left - rootElement.clientLeft) / scaleX,
			y: (center.y - rect.top - rootElement.clientTop) / scaleY
		}
	};
}
//#endregion
//#region node_modules/mjolnir.js/dist/utils/event-registrar.js
var DEFAULT_OPTIONS = {
	srcElement: "root",
	priority: 0
};
var EventRegistrar = class {
	constructor(eventManager, recognizerName) {
		/**
		* Handles hammerjs event
		*/
		this.handleEvent = (event) => {
			if (this.isEmpty()) return;
			const mjolnirEvent = this._normalizeEvent(event);
			let target = event.srcEvent.target;
			while (target && target !== mjolnirEvent.rootElement) {
				this._emit(mjolnirEvent, target);
				if (mjolnirEvent.handled) return;
				target = target.parentNode;
			}
			this._emit(mjolnirEvent, "root");
		};
		this.eventManager = eventManager;
		this.recognizerName = recognizerName;
		this.handlers = [];
		this.handlersByElement = /* @__PURE__ */ new Map();
		this._active = false;
	}
	isEmpty() {
		return !this._active;
	}
	add(type, handler, options, once = false, passive = false) {
		const { handlers, handlersByElement } = this;
		const opts = {
			...DEFAULT_OPTIONS,
			...options
		};
		let entries = handlersByElement.get(opts.srcElement);
		if (!entries) {
			entries = [];
			handlersByElement.set(opts.srcElement, entries);
		}
		const entry = {
			type,
			handler,
			srcElement: opts.srcElement,
			priority: opts.priority
		};
		if (once) entry.once = true;
		if (passive) entry.passive = true;
		handlers.push(entry);
		this._active = this._active || !entry.passive;
		let insertPosition = entries.length - 1;
		while (insertPosition >= 0) {
			if (entries[insertPosition].priority >= entry.priority) break;
			insertPosition--;
		}
		entries.splice(insertPosition + 1, 0, entry);
	}
	remove(type, handler) {
		const { handlers, handlersByElement } = this;
		for (let i = handlers.length - 1; i >= 0; i--) {
			const entry = handlers[i];
			if (entry.type === type && entry.handler === handler) {
				handlers.splice(i, 1);
				const entries = handlersByElement.get(entry.srcElement);
				entries.splice(entries.indexOf(entry), 1);
				if (entries.length === 0) handlersByElement.delete(entry.srcElement);
			}
		}
		this._active = handlers.some((entry) => !entry.passive);
	}
	/**
	* Invoke handlers on a particular element
	*/
	_emit(event, srcElement) {
		const entries = this.handlersByElement.get(srcElement);
		if (entries) {
			let immediatePropagationStopped = false;
			const stopPropagation = () => {
				event.handled = true;
			};
			const stopImmediatePropagation = () => {
				event.handled = true;
				immediatePropagationStopped = true;
			};
			const entriesToRemove = [];
			for (let i = 0; i < entries.length; i++) {
				const { type, handler, once } = entries[i];
				handler({
					...event,
					type,
					stopPropagation,
					stopImmediatePropagation
				});
				if (once) entriesToRemove.push(entries[i]);
				if (immediatePropagationStopped) break;
			}
			for (let i = 0; i < entriesToRemove.length; i++) {
				const { type, handler } = entriesToRemove[i];
				this.remove(type, handler);
			}
		}
	}
	/**
	* Normalizes hammerjs and custom events to have predictable fields.
	*/
	_normalizeEvent(event) {
		const rootElement = this.eventManager.getElement();
		return {
			...event,
			...whichButtons(event),
			...getOffsetPosition(event, rootElement),
			preventDefault: () => {
				event.srcEvent.preventDefault();
			},
			stopImmediatePropagation: null,
			stopPropagation: null,
			handled: false,
			rootElement
		};
	}
};
//#endregion
//#region node_modules/mjolnir.js/dist/event-manager.js
function normalizeRecognizer(item) {
	if ("recognizer" in item) return item;
	let recognizer;
	const itemArray = Array.isArray(item) ? [...item] : [item];
	if (typeof itemArray[0] === "function") recognizer = new (itemArray.shift())(itemArray.shift() || {});
	else recognizer = itemArray.shift();
	return {
		recognizer,
		recognizeWith: typeof itemArray[0] === "string" ? [itemArray[0]] : itemArray[0],
		requireFailure: typeof itemArray[1] === "string" ? [itemArray[1]] : itemArray[1]
	};
}
var EventManager = class {
	constructor(element = null, options = {}) {
		/**
		* Handle basic events using the 'hammer.input' Hammer.js API:
		* Before running Recognizers, Hammer emits a 'hammer.input' event
		* with the basic event info. This function emits all basic events
		* aliased to the "class" of event received.
		* See constants.BASIC_EVENT_CLASSES basic event class definitions.
		*/
		this._onBasicInput = (event) => {
			this.manager.emit(event.srcEvent.type, event);
		};
		/**
		* Handle events not supported by Hammer.js,
		* and pipe back out through same (Hammer) channel used by other events.
		*/
		this._onOtherEvent = (event) => {
			this.manager.emit(event.type, event);
		};
		this.options = {
			recognizers: [],
			events: {},
			touchAction: "compute",
			tabIndex: 0,
			cssProps: {},
			...options
		};
		this.events = /* @__PURE__ */ new Map();
		this.element = element;
		this.wheelSession = new WheelGestureSession(element);
		if (!element) return;
		this.manager = new Manager(element, this.options);
		for (const item of this.options.recognizers) {
			const { recognizer, recognizeWith, requireFailure } = normalizeRecognizer(item);
			this.manager.add(recognizer);
			if (recognizeWith) recognizer.recognizeWith(recognizeWith);
			if (requireFailure) recognizer.requireFailure(requireFailure);
		}
		this.manager.on("hammer.input", this._onBasicInput);
		this.wheelInput = new WheelInput(element, this._onOtherEvent, {
			enable: false,
			wheelSession: this.wheelSession
		});
		this.moveInput = new MoveInput(element, this._onOtherEvent, { enable: false });
		this.keyInput = new KeyInput(element, this._onOtherEvent, {
			enable: false,
			tabIndex: options.tabIndex
		});
		this.contextmenuInput = new ContextmenuInput(element, this._onOtherEvent, { enable: false });
		this.on(this.options.events);
	}
	getElement() {
		return this.element;
	}
	destroy() {
		if (!this.element) {
			this.wheelSession.destroy();
			return;
		}
		this.wheelInput.destroy();
		this.wheelSession.destroy();
		this.moveInput.destroy();
		this.keyInput.destroy();
		this.contextmenuInput.destroy();
		this.manager.destroy();
	}
	/** Register an event handler function to be called on `event` */
	on(event, handler, opts) {
		this._addEventHandler(event, handler, opts, false);
	}
	once(event, handler, opts) {
		this._addEventHandler(event, handler, opts, true);
	}
	watch(event, handler, opts) {
		this._addEventHandler(event, handler, opts, false, true);
	}
	off(event, handler) {
		this._removeEventHandler(event, handler);
	}
	/**
	* Emit a custom event into the event pipeline.
	* This allows external input sources (hand tracking, game controllers,
	* voice commands, etc.) to inject events that flow through the standard
	* EventRegistrar dispatch system.
	*
	* @param event - The event to emit. Must have a `type` field matching
	*   a recognized event name (e.g., 'panmove', 'wheel', 'custom-event').
	*/
	emit(event) {
		this.manager?.emit(event.type, event);
	}
	_toggleRecognizer(name, enabled) {
		const { manager } = this;
		if (!manager) return;
		const recognizer = manager.get(name);
		if (recognizer) {
			recognizer.set({
				enable: enabled,
				wheelSession: this.wheelSession
			});
			manager.touchAction.update();
		}
		this.wheelInput?.enableEventType(name, enabled);
		this.moveInput?.enableEventType(name, enabled);
		this.keyInput?.enableEventType(name, enabled);
		this.contextmenuInput?.enableEventType(name, enabled);
	}
	/**
	* Process the event registration for a single event + handler.
	*/
	_addEventHandler(event, handler, opts, once, passive) {
		if (typeof event !== "string") {
			opts = handler;
			for (const [eventName, eventHandler] of Object.entries(event)) this._addEventHandler(eventName, eventHandler, opts, once, passive);
			return;
		}
		const { manager, events } = this;
		if (!manager) return;
		let eventRegistrar = events.get(event);
		if (!eventRegistrar) {
			const recognizerName = this._getRecognizerName(event) || event;
			eventRegistrar = new EventRegistrar(this, recognizerName);
			events.set(event, eventRegistrar);
			if (manager) manager.on(event, eventRegistrar.handleEvent);
		}
		eventRegistrar.add(event, handler, opts, once, passive);
		if (!eventRegistrar.isEmpty()) this._toggleRecognizer(eventRegistrar.recognizerName, true);
	}
	/**
	* Process the event deregistration for a single event + handler.
	*/
	_removeEventHandler(event, handler) {
		if (typeof event !== "string") {
			for (const [eventName, eventHandler] of Object.entries(event)) this._removeEventHandler(eventName, eventHandler);
			return;
		}
		const { events } = this;
		const eventRegistrar = events.get(event);
		if (!eventRegistrar) return;
		eventRegistrar.remove(event, handler);
		if (eventRegistrar.isEmpty()) {
			const { recognizerName } = eventRegistrar;
			let isRecognizerUsed = false;
			for (const eh of events.values()) if (eh.recognizerName === recognizerName && !eh.isEmpty()) {
				isRecognizerUsed = true;
				break;
			}
			if (!isRecognizerUsed) this._toggleRecognizer(recognizerName, false);
		}
	}
	_getRecognizerName(event) {
		return this.manager.recognizers.find((recognizer) => {
			return recognizer.getEventNames().includes(event);
		})?.options.event;
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/constants.js
/**
* The coordinate system that positions/dimensions are defined in.
* String constants are the public API.
* @deprecated Use string constants directly.
*/
var COORDINATE_SYSTEM = {
	/**
	* `LNGLAT` if rendering into a geospatial viewport, `CARTESIAN` otherwise
	*/
	DEFAULT: "default",
	/**
	* Positions are interpreted as [longitude, latitude, elevation]
	* longitude/latitude are in degrees, elevation is in meters.
	* Dimensions are in meters.
	*/
	LNGLAT: "lnglat",
	/**
	* Positions are interpreted as [x, y, z] in meter offsets from the coordinate origin.
	* Dimensions are in meters.
	*/
	METER_OFFSETS: "meter-offsets",
	/**
	* Positions are interpreted as [deltaLng, deltaLat, elevation] from the coordinate origin.
	* deltaLng/deltaLat are in degrees, elevation is in meters.
	* Dimensions are in meters.
	*/
	LNGLAT_OFFSETS: "lnglat-offsets",
	/**
	* Positions and dimensions are in the common units of the viewport.
	*/
	CARTESIAN: "cartesian"
};
Object.defineProperty(COORDINATE_SYSTEM, "IDENTITY", { get: () => {
	defaultLogger.deprecated("COORDINATE_SYSTEM.IDENTITY", "COORDINATE_SYSTEM.CARTESIAN")();
	return COORDINATE_SYSTEM.CARTESIAN;
} });
/**
* How coordinates are transformed from the world space into the common space.
*/
var PROJECTION_MODE = {
	/**
	* Render geospatial data in Web Mercator projection
	*/
	WEB_MERCATOR: 1,
	/**
	* Render geospatial data as a 3D globe
	*/
	GLOBE: 2,
	/**
	* (Internal use only) Web Mercator projection at high zoom
	*/
	WEB_MERCATOR_AUTO_OFFSET: 4,
	/**
	* No transformation
	*/
	IDENTITY: 0
};
var UNIT = {
	common: 0,
	meters: 1,
	pixels: 2
};
var EVENT_HANDLERS = {
	click: "onClick",
	dblclick: "onClick",
	panstart: "onDragStart",
	panmove: "onDrag",
	panend: "onDragEnd"
};
var RECOGNIZERS = {
	multipan: [PanRecognizer, {
		threshold: 10,
		direction: InputDirection.Vertical,
		pointers: 2
	}],
	pinch: [
		PinchRecognizer,
		{},
		null,
		["multipan"]
	],
	pan: [
		PanRecognizer,
		{ threshold: 1 },
		["pinch"],
		["multipan"]
	],
	dblclick: [TapRecognizer, {
		event: "dblclick",
		taps: 2
	}],
	click: [
		TapRecognizer,
		{ event: "click" },
		null,
		["dblclick"]
	]
};
//#endregion
//#region node_modules/@deck.gl/core/dist/utils/memoize.js
function isEqual(a, b) {
	if (a === b) return true;
	if (Array.isArray(a)) {
		const len = a.length;
		if (!b || b.length !== len) return false;
		for (let i = 0; i < len; i++) if (a[i] !== b[i]) return false;
		return true;
	}
	return false;
}
/**
* Speed up consecutive function calls by caching the result of calls with identical input
* https://en.wikipedia.org/wiki/Memoization
* @param {function} compute - the function to be memoized
*/
function memoize(compute) {
	let cachedArgs = {};
	let cachedResult;
	return (args) => {
		for (const key in args) if (!isEqual(args[key], cachedArgs[key])) {
			cachedResult = compute(args);
			cachedArgs = args;
			break;
		}
		return cachedResult;
	};
}
//#endregion
//#region node_modules/@deck.gl/core/dist/shaderlib/project/viewport-uniforms.js
var ZERO_VECTOR$1 = [
	0,
	0,
	0,
	0
];
var VECTOR_TO_POINT_MATRIX = [
	1,
	0,
	0,
	0,
	0,
	1,
	0,
	0,
	0,
	0,
	1,
	0,
	0,
	0,
	0,
	0
];
var IDENTITY_MATRIX = [
	1,
	0,
	0,
	0,
	0,
	1,
	0,
	0,
	0,
	0,
	1,
	0,
	0,
	0,
	0,
	1
];
var DEFAULT_PIXELS_PER_UNIT2 = [
	0,
	0,
	0
];
var DEFAULT_COORDINATE_ORIGIN = [
	0,
	0,
	0
];
/** Coordinate system constants */
var COORDINATE_SYSTEM_NUMBERS = {
	default: -1,
	cartesian: 0,
	lnglat: 1,
	"meter-offsets": 2,
	"lnglat-offsets": 3
};
function getShaderCoordinateSystem(coordinateSystem) {
	const shaderCoordinateSystem = COORDINATE_SYSTEM_NUMBERS[coordinateSystem];
	if (shaderCoordinateSystem === void 0) throw new Error(`Invalid coordinateSystem: ${coordinateSystem}`);
	return shaderCoordinateSystem;
}
var getMemoizedViewportUniforms = memoize(calculateViewportUniforms);
function getOffsetOrigin(viewport, coordinateSystem, coordinateOrigin = DEFAULT_COORDINATE_ORIGIN) {
	if (coordinateOrigin.length < 3) coordinateOrigin = [
		coordinateOrigin[0],
		coordinateOrigin[1],
		0
	];
	let shaderCoordinateOrigin = coordinateOrigin;
	let geospatialOrigin;
	let offsetMode = true;
	if (coordinateSystem === "lnglat-offsets" || coordinateSystem === "meter-offsets") geospatialOrigin = coordinateOrigin;
	else geospatialOrigin = viewport.isGeospatial ? [
		Math.fround(viewport.longitude),
		Math.fround(viewport.latitude),
		0
	] : null;
	switch (viewport.projectionMode) {
		case PROJECTION_MODE.WEB_MERCATOR:
			if (coordinateSystem === "lnglat" || coordinateSystem === "cartesian") {
				geospatialOrigin = [
					0,
					0,
					0
				];
				offsetMode = false;
			}
			break;
		case PROJECTION_MODE.WEB_MERCATOR_AUTO_OFFSET:
			if (coordinateSystem === "lnglat") shaderCoordinateOrigin = geospatialOrigin;
			else if (coordinateSystem === "cartesian") {
				shaderCoordinateOrigin = [
					Math.fround(viewport.center[0]),
					Math.fround(viewport.center[1]),
					0
				];
				geospatialOrigin = viewport.unprojectPosition(shaderCoordinateOrigin);
				shaderCoordinateOrigin[0] -= coordinateOrigin[0];
				shaderCoordinateOrigin[1] -= coordinateOrigin[1];
				shaderCoordinateOrigin[2] -= coordinateOrigin[2];
			}
			break;
		case PROJECTION_MODE.IDENTITY:
			shaderCoordinateOrigin = viewport.position.map(Math.fround);
			shaderCoordinateOrigin[2] = shaderCoordinateOrigin[2] || 0;
			break;
		case PROJECTION_MODE.GLOBE:
			offsetMode = false;
			geospatialOrigin = null;
			break;
		default: offsetMode = false;
	}
	return {
		geospatialOrigin,
		shaderCoordinateOrigin,
		offsetMode
	};
}
function calculateMatrixAndOffset(viewport, coordinateSystem, coordinateOrigin) {
	const { viewMatrixUncentered, projectionMatrix } = viewport;
	let { viewMatrix, viewProjectionMatrix } = viewport;
	let projectionCenter = ZERO_VECTOR$1;
	let originCommon = ZERO_VECTOR$1;
	let cameraPosCommon = viewport.cameraPosition;
	const { geospatialOrigin, shaderCoordinateOrigin, offsetMode } = getOffsetOrigin(viewport, coordinateSystem, coordinateOrigin);
	if (offsetMode) {
		originCommon = viewport.projectPosition(geospatialOrigin || shaderCoordinateOrigin);
		cameraPosCommon = [
			cameraPosCommon[0] - originCommon[0],
			cameraPosCommon[1] - originCommon[1],
			cameraPosCommon[2] - originCommon[2]
		];
		originCommon[3] = 1;
		projectionCenter = transformMat4([], originCommon, viewProjectionMatrix);
		viewMatrix = viewMatrixUncentered || viewMatrix;
		viewProjectionMatrix = multiply([], projectionMatrix, viewMatrix);
		viewProjectionMatrix = multiply([], viewProjectionMatrix, VECTOR_TO_POINT_MATRIX);
	}
	return {
		viewMatrix,
		viewProjectionMatrix,
		projectionCenter,
		originCommon,
		cameraPosCommon,
		shaderCoordinateOrigin,
		geospatialOrigin
	};
}
/**
* Returns uniforms for shaders based on current projection
* includes: projection matrix suitable for shaders
*
* TODO - Ensure this works with any viewport, not just WebMercatorViewports
*
* @param {WebMercatorViewport} viewport -
* @return {Float32Array} - 4x4 projection matrix that can be used in shaders
*/
function getUniformsFromViewport({ viewport, devicePixelRatio = 1, modelMatrix = null, coordinateSystem = "default", coordinateOrigin = DEFAULT_COORDINATE_ORIGIN, autoWrapLongitude = false }) {
	if (coordinateSystem === "default") coordinateSystem = viewport.isGeospatial ? "lnglat" : "cartesian";
	const uniforms = getMemoizedViewportUniforms({
		viewport,
		devicePixelRatio,
		coordinateSystem,
		coordinateOrigin
	});
	uniforms.wrapLongitude = autoWrapLongitude;
	uniforms.modelMatrix = modelMatrix || IDENTITY_MATRIX;
	return uniforms;
}
function calculateViewportUniforms({ viewport, devicePixelRatio, coordinateSystem, coordinateOrigin }) {
	const { projectionCenter, viewProjectionMatrix, originCommon, cameraPosCommon, shaderCoordinateOrigin, geospatialOrigin } = calculateMatrixAndOffset(viewport, coordinateSystem, coordinateOrigin);
	const distanceScales = viewport.getDistanceScales();
	const viewportSize = [viewport.width * devicePixelRatio, viewport.height * devicePixelRatio];
	const focalDistance = transformMat4([], [
		0,
		0,
		-viewport.focalDistance,
		1
	], viewport.projectionMatrix)[3] || 1;
	const uniforms = {
		coordinateSystem: getShaderCoordinateSystem(coordinateSystem),
		projectionMode: viewport.projectionMode,
		coordinateOrigin: shaderCoordinateOrigin,
		commonOrigin: originCommon.slice(0, 3),
		center: projectionCenter,
		pseudoMeters: Boolean(viewport._pseudoMeters),
		viewportSize,
		devicePixelRatio,
		focalDistance,
		commonUnitsPerMeter: distanceScales.unitsPerMeter,
		commonUnitsPerWorldUnit: distanceScales.unitsPerMeter,
		commonUnitsPerWorldUnit2: DEFAULT_PIXELS_PER_UNIT2,
		scale: viewport.scale,
		wrapLongitude: false,
		viewProjectionMatrix,
		modelMatrix: IDENTITY_MATRIX,
		cameraPosition: cameraPosCommon
	};
	if (geospatialOrigin) {
		const distanceScalesAtOrigin = viewport.getDistanceScales(geospatialOrigin);
		switch (coordinateSystem) {
			case "meter-offsets":
				uniforms.commonUnitsPerWorldUnit = distanceScalesAtOrigin.unitsPerMeter;
				uniforms.commonUnitsPerWorldUnit2 = distanceScalesAtOrigin.unitsPerMeter2;
				break;
			case "lnglat":
			case "lnglat-offsets":
				if (!viewport._pseudoMeters) uniforms.commonUnitsPerMeter = distanceScalesAtOrigin.unitsPerMeter;
				uniforms.commonUnitsPerWorldUnit = distanceScalesAtOrigin.unitsPerDegree;
				uniforms.commonUnitsPerWorldUnit2 = distanceScalesAtOrigin.unitsPerDegree2;
				break;
			case "cartesian":
				uniforms.commonUnitsPerWorldUnit = [
					1,
					1,
					distanceScalesAtOrigin.unitsPerMeter[2]
				];
				uniforms.commonUnitsPerWorldUnit2 = [
					0,
					0,
					distanceScalesAtOrigin.unitsPerMeter2[2]
				];
				break;
			default: break;
		}
	}
	return uniforms;
}
var projectWGSL = `\
${`\
${[
	"default",
	"lnglat",
	"meter-offsets",
	"lnglat-offsets",
	"cartesian"
].map((coordinateSystem) => `const COORDINATE_SYSTEM_${coordinateSystem.toUpperCase().replaceAll("-", "_")}: i32 = ${getShaderCoordinateSystem(coordinateSystem)};`).join("")}
${Object.keys(PROJECTION_MODE).map((key) => `const PROJECTION_MODE_${key}: i32 = ${PROJECTION_MODE[key]};`).join("")}
${Object.keys(UNIT).map((key) => `const UNIT_${key.toUpperCase()}: i32 = ${UNIT[key]};`).join("")}

const TILE_SIZE: f32 = 512.0;
const PI: f32 = 3.1415926536;
const WORLD_SCALE: f32 = TILE_SIZE / (PI * 2.0);
const ZERO_64_LOW: vec3<f32> = vec3<f32>(0.0, 0.0, 0.0);
const EARTH_RADIUS: f32 = 6370972.0; // meters
const GLOBE_RADIUS: f32 = 256.0;

// -----------------------------------------------------------------------------
// Uniform block (converted from GLSL uniform block)
// -----------------------------------------------------------------------------
struct ProjectUniforms {
  wrapLongitude: i32,
  coordinateSystem: i32,
  commonUnitsPerMeter: vec3<f32>,
  projectionMode: i32,
  scale: f32,
  commonUnitsPerWorldUnit: vec3<f32>,
  commonUnitsPerWorldUnit2: vec3<f32>,
  center: vec4<f32>,
  modelMatrix: mat4x4<f32>,
  viewProjectionMatrix: mat4x4<f32>,
  viewportSize: vec2<f32>,
  devicePixelRatio: f32,
  focalDistance: f32,
  cameraPosition: vec3<f32>,
  coordinateOrigin: vec3<f32>,
  commonOrigin: vec3<f32>,
  pseudoMeters: i32,
};

@group(0) @binding(auto)
var<uniform> project: ProjectUniforms;

// -----------------------------------------------------------------------------
// Geometry data shared across the project helpers.
// The active layer shader is responsible for populating this private module
// state before calling the project functions below.
// -----------------------------------------------------------------------------

// Structure to carry additional geometry data used by deck.gl filters.
struct Geometry {
  worldPosition: vec3<f32>,
  worldPositionAlt: vec3<f32>,
  position: vec4<f32>,
  normal: vec3<f32>,
  uv: vec2<f32>,
  pickingColor: vec3<f32>,
};

var<private> geometry: Geometry;
`}

// -----------------------------------------------------------------------------
// Functions
// -----------------------------------------------------------------------------

// Returns an adjustment factor for commonUnitsPerMeter
fn _project_size_at_latitude(lat: f32) -> f32 {
  let y = clamp(lat, -89.9, 89.9);
  return 1.0 / cos(radians(y));
}

// Overloaded version: scales a value in meters at a given latitude.
fn _project_size_at_latitude_m(meters: f32, lat: f32) -> f32 {
  return meters * project.commonUnitsPerMeter.z * _project_size_at_latitude(lat);
}

// Computes a non-linear scale factor based on geometry.
// (Note: This function relies on "geometry" being provided.)
fn project_size() -> f32 {
  if (project.projectionMode == PROJECTION_MODE_WEB_MERCATOR &&
      project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT &&
      project.pseudoMeters == 0) {
    if (geometry.position.w == 0.0) {
      return _project_size_at_latitude(geometry.worldPosition.y);
    }
    let y: f32 = geometry.position.y / TILE_SIZE * 2.0 - 1.0;
    let y2 = y * y;
    let y4 = y2 * y2;
    let y6 = y4 * y2;
    return 1.0 + 4.9348 * y2 + 4.0587 * y4 + 1.5642 * y6;
  }
  return 1.0;
}

// Overloads to scale offsets (meters to world units)
fn project_size_float(meters: f32) -> f32 {
  return meters * project.commonUnitsPerMeter.z * project_size();
}

fn project_size_vec2(meters: vec2<f32>) -> vec2<f32> {
  return meters * project.commonUnitsPerMeter.xy * project_size();
}

fn project_size_vec3(meters: vec3<f32>) -> vec3<f32> {
  return meters * project.commonUnitsPerMeter * project_size();
}

fn project_size_vec4(meters: vec4<f32>) -> vec4<f32> {
  return vec4<f32>(meters.xyz * project.commonUnitsPerMeter, meters.w);
}

// Returns a rotation matrix aligning the z‑axis with the given up vector.
fn project_get_orientation_matrix(up: vec3<f32>) -> mat3x3<f32> {
  let uz = normalize(up);
  let ux = select(
    vec3<f32>(1.0, 0.0, 0.0),
    normalize(vec3<f32>(uz.y, -uz.x, 0.0)),
    abs(uz.z) == 1.0
  );
  let uy = cross(uz, ux);
  return mat3x3<f32>(ux, uy, uz);
}

// Since WGSL does not support "out" parameters, we return a struct.
struct RotationResult {
  needsRotation: bool,
  transform: mat3x3<f32>,
};

fn project_needs_rotation(commonPosition: vec3<f32>) -> RotationResult {
  if (project.projectionMode == PROJECTION_MODE_GLOBE) {
    return RotationResult(true, project_get_orientation_matrix(commonPosition));
  } else {
    return RotationResult(false, mat3x3<f32>());  // identity alternative if needed
  };
}

// Projects a normal vector from the current coordinate system to world space.
fn project_normal(vector: vec3<f32>) -> vec3<f32> {
  let normal_modelspace = project.modelMatrix * vec4<f32>(vector, 0.0);
  var n = normalize(normal_modelspace.xyz * project.commonUnitsPerMeter);
  let rotResult = project_needs_rotation(geometry.position.xyz);
  if (rotResult.needsRotation) {
    n = rotResult.transform * n;
  }
  return n;
}

// Applies a scale offset based on y-offset (dy)
fn project_offset_(offset: vec4<f32>) -> vec4<f32> {
  let dy: f32 = offset.y;
  let commonUnitsPerWorldUnit = project.commonUnitsPerWorldUnit + project.commonUnitsPerWorldUnit2 * dy;
  return vec4<f32>(offset.xyz * commonUnitsPerWorldUnit, offset.w);
}

// Projects lng/lat coordinates to a unit tile [0,1]
fn project_mercator_(lnglat: vec2<f32>) -> vec2<f32> {
  var x = lnglat.x;
  if (project.wrapLongitude != 0) {
    x = ((x + 180.0) % 360.0) - 180.0;
  }
  let y = clamp(lnglat.y, -89.9, 89.9);
  return vec2<f32>(
    radians(x) + PI,
    PI + log(tan(PI * 0.25 + radians(y) * 0.5))
  ) * WORLD_SCALE;
}

// Projects lng/lat/z coordinates for a globe projection.
fn project_globe_(lnglatz: vec3<f32>) -> vec3<f32> {
  let lambda = radians(lnglatz.x);
  let phi = radians(lnglatz.y);
  let cosPhi = cos(phi);
  let D = (lnglatz.z / EARTH_RADIUS + 1.0) * GLOBE_RADIUS;
  return vec3<f32>(
    sin(lambda) * cosPhi,
    -cos(lambda) * cosPhi,
    sin(phi)
  ) * D;
}

// Projects positions (with an optional 64-bit low part) from the input
// coordinate system to the common space.
fn project_position_vec4_f64(position: vec4<f32>, position64Low: vec3<f32>) -> vec4<f32> {
  var position_world = project.modelMatrix * position;

  // Work around for a Mac+NVIDIA bug:
  if (project.projectionMode == PROJECTION_MODE_WEB_MERCATOR) {
    if (project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT) {
      return vec4<f32>(
        project_mercator_(position_world.xy),
        _project_size_at_latitude_m(position_world.z, position_world.y),
        position_world.w
      );
    }
    if (project.coordinateSystem == COORDINATE_SYSTEM_CARTESIAN) {
      position_world = vec4f(position_world.xyz + project.coordinateOrigin, position_world.w);
    }
  }
  if (project.projectionMode == PROJECTION_MODE_GLOBE) {
    if (project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT) {
      return vec4<f32>(
        project_globe_(position_world.xyz),
        position_world.w
      );
    }
  }
  if (project.projectionMode == PROJECTION_MODE_WEB_MERCATOR_AUTO_OFFSET) {
    if (project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT) {
      if (abs(position_world.y - project.coordinateOrigin.y) > 0.25) {
        return vec4<f32>(
          project_mercator_(position_world.xy) - project.commonOrigin.xy,
          project_size_float(position_world.z),
          position_world.w
        );
      }
    }
  }
  if (project.projectionMode == PROJECTION_MODE_IDENTITY ||
      (project.projectionMode == PROJECTION_MODE_WEB_MERCATOR_AUTO_OFFSET &&
       (project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT ||
        project.coordinateSystem == COORDINATE_SYSTEM_CARTESIAN))) {
    position_world = vec4f(position_world.xyz - project.coordinateOrigin, position_world.w);
  }

  return project_offset_(position_world) +
         project_offset_(project.modelMatrix * vec4<f32>(position64Low, 0.0));
}

// Overloaded versions for different input types.
fn project_position_vec4_f32(position: vec4<f32>) -> vec4<f32> {
  return project_position_vec4_f64(position, ZERO_64_LOW);
}

fn project_position_vec3_f64(position: vec3<f32>, position64Low: vec3<f32>) -> vec3<f32> {
  let projected_position = project_position_vec4_f64(vec4<f32>(position, 1.0), position64Low);
  return projected_position.xyz;
}

fn project_position_vec3_f32(position: vec3<f32>) -> vec3<f32> {
  let projected_position = project_position_vec4_f64(vec4<f32>(position, 1.0), ZERO_64_LOW);
  return projected_position.xyz;
}

fn project_position_vec2_f32(position: vec2<f32>) -> vec2<f32> {
  let projected_position = project_position_vec4_f64(vec4<f32>(position, 0.0, 1.0), ZERO_64_LOW);
  return projected_position.xy;
}

// Transforms a common space position to clip space.
fn project_common_position_to_clipspace_with_projection(position: vec4<f32>, viewProjectionMatrix: mat4x4<f32>, center: vec4<f32>) -> vec4<f32> {
  return viewProjectionMatrix * position + center;
}

// Uses the project viewProjectionMatrix and center.
fn project_common_position_to_clipspace(position: vec4<f32>) -> vec4<f32> {
  return project_common_position_to_clipspace_with_projection(position, project.viewProjectionMatrix, project.center);
}

// Returns a clip space offset corresponding to a given number of screen pixels.
fn project_pixel_size_to_clipspace(pixels: vec2<f32>) -> vec2<f32> {
  let offset = pixels / project.viewportSize * project.devicePixelRatio * 2.0;
  return offset * project.focalDistance;
}

fn project_meter_size_to_pixel(meters: f32) -> f32 {
  return project_size_float(meters) * project.scale;
}

fn project_unit_size_to_pixel(size: f32, unit: i32) -> f32 {
  if (unit == UNIT_METERS) {
    return project_meter_size_to_pixel(size);
  } else if (unit == UNIT_COMMON) {
    return size * project.scale;
  }
  // UNIT_PIXELS: no scaling applied.
  return size;
}

fn project_pixel_size_float(pixels: f32) -> f32 {
  return pixels / project.scale;
}

fn project_pixel_size_vec2(pixels: vec2<f32>) -> vec2<f32> {
  return pixels / project.scale;
}
`;
var projectGLSL = `\
${[
	"default",
	"lnglat",
	"meter-offsets",
	"lnglat-offsets",
	"cartesian"
].map((coordinateSystem) => `const int COORDINATE_SYSTEM_${coordinateSystem.toUpperCase().replaceAll("-", "_")} = ${getShaderCoordinateSystem(coordinateSystem)};`).join("")}
${Object.keys(PROJECTION_MODE).map((key) => `const int PROJECTION_MODE_${key} = ${PROJECTION_MODE[key]};`).join("")}
${Object.keys(UNIT).map((key) => `const int UNIT_${key.toUpperCase()} = ${UNIT[key]};`).join("")}
layout(std140) uniform projectUniforms {
bool wrapLongitude;
int coordinateSystem;
vec3 commonUnitsPerMeter;
int projectionMode;
float scale;
vec3 commonUnitsPerWorldUnit;
vec3 commonUnitsPerWorldUnit2;
vec4 center;
mat4 modelMatrix;
mat4 viewProjectionMatrix;
vec2 viewportSize;
float devicePixelRatio;
float focalDistance;
vec3 cameraPosition;
vec3 coordinateOrigin;
vec3 commonOrigin;
bool pseudoMeters;
} project;
const float TILE_SIZE = 512.0;
const float PI = 3.1415926536;
const float WORLD_SCALE = TILE_SIZE / (PI * 2.0);
const vec3 ZERO_64_LOW = vec3(0.0);
const float EARTH_RADIUS = 6370972.0;
const float GLOBE_RADIUS = 256.0;
float project_size_at_latitude(float lat) {
float y = clamp(lat, -89.9, 89.9);
return 1.0 / cos(radians(y));
}
float project_size() {
if (project.projectionMode == PROJECTION_MODE_WEB_MERCATOR &&
project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT &&
project.pseudoMeters == false) {
if (geometry.position.w == 0.0) {
return project_size_at_latitude(geometry.worldPosition.y);
}
float y = geometry.position.y / TILE_SIZE * 2.0 - 1.0;
float y2 = y * y;
float y4 = y2 * y2;
float y6 = y4 * y2;
return 1.0 + 4.9348 * y2 + 4.0587 * y4 + 1.5642 * y6;
}
return 1.0;
}
float project_size_at_latitude(float meters, float lat) {
return meters * project.commonUnitsPerMeter.z * project_size_at_latitude(lat);
}
float project_size(float meters) {
return meters * project.commonUnitsPerMeter.z * project_size();
}
vec2 project_size(vec2 meters) {
return meters * project.commonUnitsPerMeter.xy * project_size();
}
vec3 project_size(vec3 meters) {
return meters * project.commonUnitsPerMeter * project_size();
}
vec4 project_size(vec4 meters) {
return vec4(meters.xyz * project.commonUnitsPerMeter, meters.w);
}
mat3 project_get_orientation_matrix(vec3 up) {
vec3 uz = normalize(up);
vec3 ux = abs(uz.z) == 1.0 ? vec3(1.0, 0.0, 0.0) : normalize(vec3(uz.y, -uz.x, 0));
vec3 uy = cross(uz, ux);
return mat3(ux, uy, uz);
}
bool project_needs_rotation(vec3 commonPosition, out mat3 transform) {
if (project.projectionMode == PROJECTION_MODE_GLOBE) {
transform = project_get_orientation_matrix(commonPosition);
return true;
}
return false;
}
vec3 project_normal(vec3 vector) {
vec4 normal_modelspace = project.modelMatrix * vec4(vector, 0.0);
vec3 n = normalize(normal_modelspace.xyz * project.commonUnitsPerMeter);
mat3 rotation;
if (project_needs_rotation(geometry.position.xyz, rotation)) {
n = rotation * n;
}
return n;
}
vec4 project_offset_(vec4 offset) {
float dy = offset.y;
vec3 commonUnitsPerWorldUnit = project.commonUnitsPerWorldUnit + project.commonUnitsPerWorldUnit2 * dy;
return vec4(offset.xyz * commonUnitsPerWorldUnit, offset.w);
}
vec2 project_mercator_(vec2 lnglat) {
float x = lnglat.x;
if (project.wrapLongitude) {
x = mod(x + 180., 360.0) - 180.;
}
float y = clamp(lnglat.y, -89.9, 89.9);
return vec2(
radians(x) + PI,
PI + log(tan_fp32(PI * 0.25 + radians(y) * 0.5))
) * WORLD_SCALE;
}
vec3 project_globe_(vec3 lnglatz) {
float lambda = radians(lnglatz.x);
float phi = radians(lnglatz.y);
float cosPhi = cos(phi);
float D = (lnglatz.z / EARTH_RADIUS + 1.0) * GLOBE_RADIUS;
return vec3(
sin(lambda) * cosPhi,
-cos(lambda) * cosPhi,
sin(phi)
) * D;
}
vec4 project_position(vec4 position, vec3 position64Low) {
vec4 position_world = project.modelMatrix * position;
if (project.projectionMode == PROJECTION_MODE_WEB_MERCATOR) {
if (project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT) {
return vec4(
project_mercator_(position_world.xy),
project_size_at_latitude(position_world.z, position_world.y),
position_world.w
);
}
if (project.coordinateSystem == COORDINATE_SYSTEM_CARTESIAN) {
position_world.xyz += project.coordinateOrigin;
}
}
if (project.projectionMode == PROJECTION_MODE_GLOBE) {
if (project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT) {
return vec4(
project_globe_(position_world.xyz),
position_world.w
);
}
}
if (project.projectionMode == PROJECTION_MODE_WEB_MERCATOR_AUTO_OFFSET) {
if (project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT) {
if (abs(position_world.y - project.coordinateOrigin.y) > 0.25) {
return vec4(
project_mercator_(position_world.xy) - project.commonOrigin.xy,
project_size(position_world.z),
position_world.w
);
}
}
}
if (project.projectionMode == PROJECTION_MODE_IDENTITY ||
(project.projectionMode == PROJECTION_MODE_WEB_MERCATOR_AUTO_OFFSET &&
(project.coordinateSystem == COORDINATE_SYSTEM_LNGLAT ||
project.coordinateSystem == COORDINATE_SYSTEM_CARTESIAN))) {
position_world.xyz -= project.coordinateOrigin;
}
return project_offset_(position_world) + project_offset_(project.modelMatrix * vec4(position64Low, 0.0));
}
vec4 project_position(vec4 position) {
return project_position(position, ZERO_64_LOW);
}
vec3 project_position(vec3 position, vec3 position64Low) {
vec4 projected_position = project_position(vec4(position, 1.0), position64Low);
return projected_position.xyz;
}
vec3 project_position(vec3 position) {
vec4 projected_position = project_position(vec4(position, 1.0), ZERO_64_LOW);
return projected_position.xyz;
}
vec2 project_position(vec2 position) {
vec4 projected_position = project_position(vec4(position, 0.0, 1.0), ZERO_64_LOW);
return projected_position.xy;
}
vec4 project_common_position_to_clipspace(vec4 position, mat4 viewProjectionMatrix, vec4 center) {
return viewProjectionMatrix * position + center;
}
vec4 project_common_position_to_clipspace(vec4 position) {
return project_common_position_to_clipspace(position, project.viewProjectionMatrix, project.center);
}
vec2 project_pixel_size_to_clipspace(vec2 pixels) {
vec2 offset = pixels / project.viewportSize * project.devicePixelRatio * 2.0;
return offset * project.focalDistance;
}
float project_size_to_pixel(float meters) {
return project_size(meters) * project.scale;
}
vec2 project_size_to_pixel(vec2 meters) {
return project_size(meters) * project.scale;
}
float project_size_to_pixel(float size, int unit) {
if (unit == UNIT_METERS) return project_size_to_pixel(size);
if (unit == UNIT_COMMON) return size * project.scale;
return size;
}
float project_pixel_size(float pixels) {
return pixels / project.scale;
}
vec2 project_pixel_size(vec2 pixels) {
return pixels / project.scale;
}
`;
//#endregion
//#region node_modules/@deck.gl/core/dist/shaderlib/project/project.js
var INITIAL_MODULE_OPTIONS = {};
function getUniforms(opts = INITIAL_MODULE_OPTIONS) {
	if ("viewport" in opts) return getUniformsFromViewport(opts);
	return {};
}
var project_default = {
	name: "project",
	dependencies: [fp32, geometry_default],
	source: projectWGSL,
	vs: projectGLSL,
	getUniforms,
	uniformTypes: {
		wrapLongitude: "f32",
		coordinateSystem: "i32",
		commonUnitsPerMeter: "vec3<f32>",
		projectionMode: "i32",
		scale: "f32",
		commonUnitsPerWorldUnit: "vec3<f32>",
		commonUnitsPerWorldUnit2: "vec3<f32>",
		center: "vec4<f32>",
		modelMatrix: "mat4x4<f32>",
		viewProjectionMatrix: "mat4x4<f32>",
		viewportSize: "vec2<f32>",
		devicePixelRatio: "f32",
		focalDistance: "f32",
		cameraPosition: "vec3<f32>",
		coordinateOrigin: "vec3<f32>",
		commonOrigin: "vec3<f32>",
		pseudoMeters: "f32"
	}
};
var project32_default = {
	name: "project32",
	dependencies: [project_default],
	source: `\
// Define a structure to hold both the clip-space position and the common position.
struct ProjectResult {
  clipPosition: vec4<f32>,
  commonPosition: vec4<f32>,
};

// This function mimics the GLSL version with the 'out' parameter by returning both values.
fn project_position_to_clipspace_and_commonspace(
    position: vec3<f32>,
    position64Low: vec3<f32>,
    offset: vec3<f32>
) -> ProjectResult {
  // Compute the projected position.
  let projectedPosition: vec3<f32> = project_position_vec3_f64(position, position64Low);

  // Start with the provided offset.
  var finalOffset: vec3<f32> = offset;

  // Get whether a rotation is needed and the rotation matrix.
  let rotationResult = project_needs_rotation(projectedPosition);

  // If rotation is needed, update the offset.
  if (rotationResult.needsRotation) {
    finalOffset = rotationResult.transform * offset;
  }

  // Compute the common position.
  let commonPosition: vec4<f32> = vec4<f32>(projectedPosition + finalOffset, 1.0);

  // Convert to clip-space.
  let clipPosition: vec4<f32> = project_common_position_to_clipspace(commonPosition);

  return ProjectResult(clipPosition, commonPosition);
}

// A convenience overload that returns only the clip-space position.
fn project_position_to_clipspace(
    position: vec3<f32>,
    position64Low: vec3<f32>,
    offset: vec3<f32>
) -> vec4<f32> {
  return project_position_to_clipspace_and_commonspace(position, position64Low, offset).clipPosition;
}
`,
	vs: `\
vec4 project_position_to_clipspace(
  vec3 position, vec3 position64Low, vec3 offset, out vec4 commonPosition
) {
  vec3 projectedPosition = project_position(position, position64Low);
  mat3 rotation;
  if (project_needs_rotation(projectedPosition, rotation)) {
    // offset is specified as ENU
    // when in globe projection, rotate offset so that the ground alighs with the surface of the globe
    offset = rotation * offset;
  }
  commonPosition = vec4(projectedPosition + offset, 1.0);
  return project_common_position_to_clipspace(commonPosition);
}

vec4 project_position_to_clipspace(
  vec3 position, vec3 position64Low, vec3 offset
) {
  vec4 commonPosition;
  return project_position_to_clipspace(position, position64Low, offset, commonPosition);
}
`
};
//#endregion
//#region node_modules/@math.gl/web-mercator/dist/math-utils.js
function createMat4$1() {
	return [
		1,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		1
	];
}
function transformVector(matrix, vector) {
	const result = transformMat4([], vector, matrix);
	scale(result, result, 1 / result[3]);
	return result;
}
function clamp(x, min, max) {
	return x < min ? min : x > max ? max : x;
}
function ieLog2(x) {
	return Math.log(x) * Math.LOG2E;
}
var log2 = Math.log2 || ieLog2;
//#endregion
//#region node_modules/@math.gl/web-mercator/dist/assert.js
function assert$1(condition, message) {
	if (!condition) throw new Error(message || "@math.gl/web-mercator: assertion failed.");
}
//#endregion
//#region node_modules/@math.gl/web-mercator/dist/web-mercator-utils.js
var PI = Math.PI;
var PI_4 = PI / 4;
var DEGREES_TO_RADIANS$2 = PI / 180;
var RADIANS_TO_DEGREES = 180 / PI;
var TILE_SIZE = 512;
var EARTH_CIRCUMFERENCE = 4003e4;
var MAX_LATITUDE = 85.051129;
var DEFAULT_ALTITUDE = 1.5;
/** Linear scale to logarithimic zoom **/
function scaleToZoom(scale) {
	return log2(scale);
}
/**
* Project [lng,lat] on sphere onto [x,y] on 512*512 Mercator Zoom 0 tile.
* Performs the nonlinear part of the web mercator projection.
* Remaining projection is done with 4x4 matrices which also handles
* perspective.
*
* @param lngLat - [lng, lat] coordinates
*   Specifies a point on the sphere to project onto the map.
* @return [x,y] coordinates.
*/
function lngLatToWorld(lngLat) {
	const [lng, lat] = lngLat;
	assert$1(Number.isFinite(lng));
	assert$1(Number.isFinite(lat) && lat >= -90 && lat <= 90, "invalid latitude");
	const lambda2 = lng * DEGREES_TO_RADIANS$2;
	const phi2 = lat * DEGREES_TO_RADIANS$2;
	return [TILE_SIZE * (lambda2 + PI) / (2 * PI), TILE_SIZE * (PI + Math.log(Math.tan(PI_4 + phi2 * .5))) / (2 * PI)];
}
/**
* Unproject world point [x,y] on map onto {lat, lon} on sphere
*
* @param xy - array with [x,y] members
*  representing point on projected map plane
* @return - array with [x,y] of point on sphere.
*   Has toArray method if you need a GeoJSON Array.
*   Per cartographic tradition, lat and lon are specified as degrees.
*/
function worldToLngLat(xy) {
	const [x, y] = xy;
	const lambda2 = x / TILE_SIZE * (2 * PI) - PI;
	const phi2 = 2 * (Math.atan(Math.exp(y / TILE_SIZE * (2 * PI) - PI)) - PI_4);
	return [lambda2 * RADIANS_TO_DEGREES, phi2 * RADIANS_TO_DEGREES];
}
/**
* Returns the zoom level that gives a 1 meter pixel at a certain latitude
* 1 = C*cos(y)/2^z/TILE_SIZE = C*cos(y)/2^(z+9)
*/
function getMeterZoom(options) {
	const { latitude } = options;
	assert$1(Number.isFinite(latitude));
	return scaleToZoom(EARTH_CIRCUMFERENCE * Math.cos(latitude * DEGREES_TO_RADIANS$2)) - 9;
}
/**
* Calculate the conversion from meter to common units at a given latitude
* This is a cheaper version of `getDistanceScales`
* @param latitude center latitude in degrees
* @returns common units per meter
*/
function unitsPerMeter(latitude) {
	const latCosine = Math.cos(latitude * DEGREES_TO_RADIANS$2);
	return TILE_SIZE / EARTH_CIRCUMFERENCE / latCosine;
}
/**
* Calculate distance scales in meters around current lat/lon, both for
* degrees and pixels.
* In mercator projection mode, the distance scales vary significantly
* with latitude.
*/
function getDistanceScales(options) {
	const { latitude, longitude, highPrecision = false } = options;
	assert$1(Number.isFinite(latitude) && Number.isFinite(longitude));
	const worldSize = TILE_SIZE;
	const latCosine = Math.cos(latitude * DEGREES_TO_RADIANS$2);
	/**
	* Number of pixels occupied by one degree longitude around current lat/lon:
	unitsPerDegreeX = d(lngLatToWorld([lng, lat])[0])/d(lng)
	= scale * TILE_SIZE * DEGREES_TO_RADIANS / (2 * PI)
	unitsPerDegreeY = d(lngLatToWorld([lng, lat])[1])/d(lat)
	= -scale * TILE_SIZE * DEGREES_TO_RADIANS / cos(lat * DEGREES_TO_RADIANS)  / (2 * PI)
	*/
	const unitsPerDegreeX = worldSize / 360;
	const unitsPerDegreeY = unitsPerDegreeX / latCosine;
	/**
	* Number of pixels occupied by one meter around current lat/lon:
	*/
	const altUnitsPerMeter = worldSize / EARTH_CIRCUMFERENCE / latCosine;
	/**
	* LngLat: longitude -> east and latitude -> north (bottom left)
	* UTM meter offset: x -> east and y -> north (bottom left)
	* World space: x -> east and y -> south (top left)
	*
	* Y needs to be flipped when converting delta degree/meter to delta pixels
	*/
	const result = {
		unitsPerMeter: [
			altUnitsPerMeter,
			altUnitsPerMeter,
			altUnitsPerMeter
		],
		metersPerUnit: [
			1 / altUnitsPerMeter,
			1 / altUnitsPerMeter,
			1 / altUnitsPerMeter
		],
		unitsPerDegree: [
			unitsPerDegreeX,
			unitsPerDegreeY,
			altUnitsPerMeter
		],
		degreesPerUnit: [
			1 / unitsPerDegreeX,
			1 / unitsPerDegreeY,
			1 / altUnitsPerMeter
		]
	};
	/**
	* Taylor series 2nd order for 1/latCosine
	f'(a) * (x - a)
	= d(1/cos(lat * DEGREES_TO_RADIANS))/d(lat) * dLat
	= DEGREES_TO_RADIANS * tan(lat * DEGREES_TO_RADIANS) / cos(lat * DEGREES_TO_RADIANS) * dLat
	*/
	if (highPrecision) {
		const latCosine2 = DEGREES_TO_RADIANS$2 * Math.tan(latitude * DEGREES_TO_RADIANS$2) / latCosine;
		const unitsPerDegreeY2 = unitsPerDegreeX * latCosine2 / 2;
		const altUnitsPerDegree2 = worldSize / EARTH_CIRCUMFERENCE * latCosine2;
		const altUnitsPerMeter2 = altUnitsPerDegree2 / unitsPerDegreeY * altUnitsPerMeter;
		result.unitsPerDegree2 = [
			0,
			unitsPerDegreeY2,
			altUnitsPerDegree2
		];
		result.unitsPerMeter2 = [
			altUnitsPerMeter2,
			0,
			altUnitsPerMeter2
		];
	}
	return result;
}
/**
* Offset a lng/lat position by meterOffset (northing, easting)
*/
function addMetersToLngLat(lngLatZ, xyz) {
	const [longitude, latitude, z0] = lngLatZ;
	const [x, y, z] = xyz;
	const { unitsPerMeter, unitsPerMeter2 } = getDistanceScales({
		longitude,
		latitude,
		highPrecision: true
	});
	const worldspace = lngLatToWorld(lngLatZ);
	worldspace[0] += x * (unitsPerMeter[0] + unitsPerMeter2[0] * y);
	worldspace[1] += y * (unitsPerMeter[1] + unitsPerMeter2[1] * y);
	const newLngLat = worldToLngLat(worldspace);
	const newZ = (z0 || 0) + (z || 0);
	return Number.isFinite(z0) || Number.isFinite(z) ? [
		newLngLat[0],
		newLngLat[1],
		newZ
	] : newLngLat;
}
/**
*
* view and projection matrix creation is intentionally kept compatible with
* mapbox-gl's implementation to ensure that seamless interoperation
* with mapbox and react-map-gl. See: https://github.com/mapbox/mapbox-gl-js
*/
function getViewMatrix(options) {
	const { height, pitch, bearing, altitude, scale, center } = options;
	const vm = createMat4$1();
	translate(vm, vm, [
		0,
		0,
		-altitude
	]);
	rotateX(vm, vm, -pitch * DEGREES_TO_RADIANS$2);
	rotateZ(vm, vm, bearing * DEGREES_TO_RADIANS$2);
	const relativeScale = scale / height;
	scale$1(vm, vm, [
		relativeScale,
		relativeScale,
		relativeScale
	]);
	if (center) translate(vm, vm, negate([], center));
	return vm;
}
/**
* Calculates mapbox compatible projection matrix from parameters
*
* @param options.width Width of "viewport" or window
* @param options.height Height of "viewport" or window
* @param options.scale Scale at the current zoom
* @param options.center Offset of the target, vec3 in world space
* @param options.offset Offset of the focal point, vec2 in screen space
* @param options.pitch Camera angle in degrees (0 is straight down)
* @param options.fovy field of view in degrees
* @param options.altitude if provided, field of view is calculated using `altitudeToFovy()`
* @param options.nearZMultiplier control z buffer
* @param options.farZMultiplier control z buffer
* @returns project parameters object
*/
function getProjectionParameters(options) {
	const { width, height, altitude, pitch = 0, offset, center, scale, nearZMultiplier = 1, farZMultiplier = 1 } = options;
	let { fovy = altitudeToFovy(DEFAULT_ALTITUDE) } = options;
	if (altitude !== void 0) fovy = altitudeToFovy(altitude);
	const fovRadians = fovy * DEGREES_TO_RADIANS$2;
	const pitchRadians = pitch * DEGREES_TO_RADIANS$2;
	const focalDistance = fovyToAltitude(fovy);
	let cameraToSeaLevelDistance = focalDistance;
	if (center) cameraToSeaLevelDistance += center[2] * scale / Math.cos(pitchRadians) / height;
	const fovAboveCenter = fovRadians * (.5 + (offset ? offset[1] : 0) / height);
	const topHalfSurfaceDistance = Math.sin(fovAboveCenter) * cameraToSeaLevelDistance / Math.sin(clamp(Math.PI / 2 - pitchRadians - fovAboveCenter, .01, Math.PI - .01));
	const furthestDistance = Math.sin(pitchRadians) * topHalfSurfaceDistance + cameraToSeaLevelDistance;
	const horizonDistance = cameraToSeaLevelDistance * 10;
	const farZ = Math.min(furthestDistance * farZMultiplier, horizonDistance);
	return {
		fov: fovRadians,
		aspect: width / height,
		focalDistance,
		near: nearZMultiplier,
		far: farZ
	};
}
/**
*
* Convert an altitude to field of view such that the
* focal distance is equal to the altitude
*
* @param altitude - altitude of camera in screen units
* @return fovy field of view in degrees
*/
function altitudeToFovy(altitude) {
	return 2 * Math.atan(.5 / altitude) * RADIANS_TO_DEGREES;
}
/**
*
* Convert an field of view such that the
* focal distance is equal to the altitude
*
* @param fovy - field of view in degrees
* @return altitude altitude of camera in screen units
*/
function fovyToAltitude(fovy) {
	return .5 / Math.tan(.5 * fovy * DEGREES_TO_RADIANS$2);
}
function worldToPixels(xyz, pixelProjectionMatrix) {
	const [x, y, z = 0] = xyz;
	assert$1(Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(z));
	return transformVector(pixelProjectionMatrix, [
		x,
		y,
		z,
		1
	]);
}
/**
* Unproject pixels on screen to flat coordinates.
*
* @param xyz - pixel coordinate on screen.
* @param pixelUnprojectionMatrix - unprojection matrix 4x4
* @param targetZ - if pixel coordinate does not have a 3rd component (depth),
*    targetZ is used as the elevation plane to unproject onto
* @return [x, y, Z] flat coordinates on 512*512 Mercator Zoom 0 tile.
*/
function pixelsToWorld(xyz, pixelUnprojectionMatrix, targetZ = 0) {
	const [x, y, z] = xyz;
	assert$1(Number.isFinite(x) && Number.isFinite(y), "invalid pixel coordinate");
	if (Number.isFinite(z)) return transformVector(pixelUnprojectionMatrix, [
		x,
		y,
		z,
		1
	]);
	const coord0 = transformVector(pixelUnprojectionMatrix, [
		x,
		y,
		0,
		1
	]);
	const coord1 = transformVector(pixelUnprojectionMatrix, [
		x,
		y,
		1,
		1
	]);
	const z0 = coord0[2];
	const z1 = coord1[2];
	return lerp$1([], coord0, coord1, z0 === z1 ? 0 : ((targetZ || 0) - z0) / (z1 - z0));
}
//#endregion
//#region node_modules/@math.gl/web-mercator/dist/fit-bounds.js
/**
* Returns map settings {latitude, longitude, zoom}
* that will contain the provided corners within the provided width.
*
* > _Note: Only supports non-perspective mode._
*
* @param options fit bounds parameters
* @returns - latitude, longitude and zoom
*/
function fitBounds(options) {
	const { width, height, bounds, minExtent = 0, maxZoom = 24, offset = [0, 0] } = options;
	const [[west, south], [east, north]] = bounds;
	const padding = getPaddingObject(options.padding);
	const nw = lngLatToWorld([west, clamp(north, -MAX_LATITUDE, MAX_LATITUDE)]);
	const se = lngLatToWorld([east, clamp(south, -MAX_LATITUDE, MAX_LATITUDE)]);
	const size = [Math.max(Math.abs(se[0] - nw[0]), minExtent), Math.max(Math.abs(se[1] - nw[1]), minExtent)];
	const targetSize = [width - padding.left - padding.right - Math.abs(offset[0]) * 2, height - padding.top - padding.bottom - Math.abs(offset[1]) * 2];
	assert$1(targetSize[0] > 0 && targetSize[1] > 0);
	const scaleX = targetSize[0] / size[0];
	const scaleY = targetSize[1] / size[1];
	const offsetX = (padding.right - padding.left) / 2 / scaleX;
	const offsetY = (padding.top - padding.bottom) / 2 / scaleY;
	const centerLngLat = worldToLngLat([(se[0] + nw[0]) / 2 + offsetX, (se[1] + nw[1]) / 2 + offsetY]);
	const zoom = Math.min(maxZoom, log2(Math.abs(Math.min(scaleX, scaleY))));
	assert$1(Number.isFinite(zoom));
	return {
		longitude: centerLngLat[0],
		latitude: centerLngLat[1],
		zoom
	};
}
function getPaddingObject(padding = 0) {
	if (typeof padding === "number") return {
		top: padding,
		bottom: padding,
		left: padding,
		right: padding
	};
	assert$1(Number.isFinite(padding.top) && Number.isFinite(padding.bottom) && Number.isFinite(padding.left) && Number.isFinite(padding.right));
	return padding;
}
//#endregion
//#region node_modules/@math.gl/web-mercator/dist/get-bounds.js
var DEGREES_TO_RADIANS$1 = Math.PI / 180;
function getBounds(viewport, z = 0) {
	const { width, height, unproject } = viewport;
	const unprojectOps = { targetZ: z };
	const bottomLeft = unproject([0, height], unprojectOps);
	const bottomRight = unproject([width, height], unprojectOps);
	let topLeft;
	let topRight;
	if ((viewport.fovy ? .5 * viewport.fovy * DEGREES_TO_RADIANS$1 : Math.atan(.5 / viewport.altitude)) > (90 - viewport.pitch) * DEGREES_TO_RADIANS$1 - .01) {
		topLeft = unprojectOnFarPlane(viewport, 0, z);
		topRight = unprojectOnFarPlane(viewport, width, z);
	} else {
		topLeft = unproject([0, 0], unprojectOps);
		topRight = unproject([width, 0], unprojectOps);
	}
	return [
		bottomLeft,
		bottomRight,
		topRight,
		topLeft
	];
}
function unprojectOnFarPlane(viewport, x, targetZ) {
	const { pixelUnprojectionMatrix } = viewport;
	const coord0 = transformVector(pixelUnprojectionMatrix, [
		x,
		0,
		1,
		1
	]);
	const coord1 = transformVector(pixelUnprojectionMatrix, [
		x,
		viewport.height,
		1,
		1
	]);
	const result = worldToLngLat(lerp$1([], coord0, coord1, (targetZ * viewport.distanceScales.unitsPerMeter[2] - coord0[2]) / (coord1[2] - coord0[2])));
	result.push(targetZ);
	return result;
}
//#endregion
//#region node_modules/@deck.gl/core/dist/shaderlib/picking/picking.js
var sourceWGSL = `\
struct pickingUniforms {
  isActive: f32,
  isAttribute: f32,
  isHighlightActive: f32,
  useByteColors: f32,
  highlightedObjectColor: vec3<f32>,
  highlightColor: vec4<f32>,
};

@group(0) @binding(auto) var<uniform> picking: pickingUniforms;

fn picking_normalizeColor(color: vec3<f32>) -> vec3<f32> {
  return select(color, color / 255.0, picking.useByteColors > 0.5);
}

fn picking_normalizeColor4(color: vec4<f32>) -> vec4<f32> {
  return select(color, color / 255.0, picking.useByteColors > 0.5);
}

fn picking_isColorZero(color: vec3<f32>) -> bool {
  return dot(color, vec3<f32>(1.0)) < 0.00001;
}

fn picking_isColorValid(color: vec3<f32>) -> bool {
  return dot(color, vec3<f32>(1.0)) > 0.00001;
}
`;
var picking_default = {
	...picking,
	source: sourceWGSL,
	defaultUniforms: {
		...picking.defaultUniforms,
		useByteColors: true
	},
	inject: {
		"vs:DECKGL_FILTER_GL_POSITION": `
    // for picking depth values
    picking_setPickingAttribute(position.z / position.w);
  `,
		"vs:DECKGL_FILTER_COLOR": `
  picking_setPickingColor(geometry.pickingColor);
  `,
		"fs:DECKGL_FILTER_COLOR": {
			order: 99,
			injection: `
  // use highlight color if this fragment belongs to the selected object.
  color = picking_filterHighlightColor(color);

  // use picking color if rendering to picking FBO.
  color = picking_filterPickingColor(color);
    `
		}
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/utils/typed-array-manager.js
var TypedArrayManager = class {
	constructor(options = {}) {
		this._pool = [];
		this.opts = {
			overAlloc: 2,
			poolSize: 100
		};
		this.setOptions(options);
	}
	setOptions(options) {
		Object.assign(this.opts, options);
	}
	allocate(typedArray, count, { size = 1, type, padding = 0, copy = false, initialize = false, maxCount }) {
		const Type = type || typedArray && typedArray.constructor || Float32Array;
		const newSize = count * size + padding;
		if (ArrayBuffer.isView(typedArray)) {
			if (newSize <= typedArray.length) return typedArray;
			if (newSize * typedArray.BYTES_PER_ELEMENT <= typedArray.buffer.byteLength) return new Type(typedArray.buffer, 0, newSize);
		}
		let maxSize = Infinity;
		if (maxCount) maxSize = maxCount * size + padding;
		const newArray = this._allocate(Type, newSize, initialize, maxSize);
		if (typedArray && copy) newArray.set(typedArray);
		else if (!initialize) newArray.fill(0, 0, 4);
		this._release(typedArray);
		return newArray;
	}
	release(typedArray) {
		this._release(typedArray);
	}
	_allocate(Type, size, initialize, maxSize) {
		let sizeToAllocate = Math.max(Math.ceil(size * this.opts.overAlloc), 1);
		if (sizeToAllocate > maxSize) sizeToAllocate = maxSize;
		const pool = this._pool;
		const byteLength = Type.BYTES_PER_ELEMENT * sizeToAllocate;
		const i = pool.findIndex((b) => b.byteLength >= byteLength);
		if (i >= 0) {
			const array = new Type(pool.splice(i, 1)[0], 0, sizeToAllocate);
			if (initialize) array.fill(0);
			return array;
		}
		return new Type(sizeToAllocate);
	}
	_release(typedArray) {
		if (!ArrayBuffer.isView(typedArray)) return;
		const pool = this._pool;
		const { buffer } = typedArray;
		const { byteLength } = buffer;
		const i = pool.findIndex((b) => b.byteLength >= byteLength);
		if (i < 0) pool.push(buffer);
		else if (i > 0 || pool.length < this.opts.poolSize) pool.splice(i, 0, buffer);
		if (pool.length > this.opts.poolSize) pool.shift();
	}
};
var typed_array_manager_default = new TypedArrayManager();
//#endregion
//#region node_modules/@deck.gl/core/dist/utils/math-utils.js
function createMat4() {
	return [
		1,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		1
	];
}
function mod(value, divisor) {
	const modulus = value % divisor;
	return modulus < 0 ? divisor + modulus : modulus;
}
function getCameraPosition(viewMatrixInverse) {
	return [
		viewMatrixInverse[12],
		viewMatrixInverse[13],
		viewMatrixInverse[14]
	];
}
function getFrustumPlanes(viewProjectionMatrix) {
	return {
		left: getFrustumPlane(viewProjectionMatrix[3] + viewProjectionMatrix[0], viewProjectionMatrix[7] + viewProjectionMatrix[4], viewProjectionMatrix[11] + viewProjectionMatrix[8], viewProjectionMatrix[15] + viewProjectionMatrix[12]),
		right: getFrustumPlane(viewProjectionMatrix[3] - viewProjectionMatrix[0], viewProjectionMatrix[7] - viewProjectionMatrix[4], viewProjectionMatrix[11] - viewProjectionMatrix[8], viewProjectionMatrix[15] - viewProjectionMatrix[12]),
		bottom: getFrustumPlane(viewProjectionMatrix[3] + viewProjectionMatrix[1], viewProjectionMatrix[7] + viewProjectionMatrix[5], viewProjectionMatrix[11] + viewProjectionMatrix[9], viewProjectionMatrix[15] + viewProjectionMatrix[13]),
		top: getFrustumPlane(viewProjectionMatrix[3] - viewProjectionMatrix[1], viewProjectionMatrix[7] - viewProjectionMatrix[5], viewProjectionMatrix[11] - viewProjectionMatrix[9], viewProjectionMatrix[15] - viewProjectionMatrix[13]),
		near: getFrustumPlane(viewProjectionMatrix[3] + viewProjectionMatrix[2], viewProjectionMatrix[7] + viewProjectionMatrix[6], viewProjectionMatrix[11] + viewProjectionMatrix[10], viewProjectionMatrix[15] + viewProjectionMatrix[14]),
		far: getFrustumPlane(viewProjectionMatrix[3] - viewProjectionMatrix[2], viewProjectionMatrix[7] - viewProjectionMatrix[6], viewProjectionMatrix[11] - viewProjectionMatrix[10], viewProjectionMatrix[15] - viewProjectionMatrix[14])
	};
}
var scratchVector = new Vector3();
function getFrustumPlane(a, b, c, d) {
	scratchVector.set(a, b, c);
	const L = scratchVector.len();
	return {
		distance: d / L,
		normal: new Vector3(-a / L, -b / L, -c / L)
	};
}
/**
* Calculate the low part of a WebGL 64 bit float
* @param x {number} - the input float number
* @returns {number} - the lower 32 bit of the number
*/
function fp64LowPart(x) {
	return x - Math.fround(x);
}
var scratchArray;
/**
* Split a Float64Array into a double-length Float32Array
* @param typedArray
* @param options
* @param options.size  - per attribute size
* @param options.startIndex - start index in the source array
* @param options.endIndex  - end index in the source array
* @returns {} - high part, low part for each attribute:
[1xHi, 1yHi, 1zHi, 1xLow, 1yLow, 1zLow, 2xHi, ...]
*/
function toDoublePrecisionArray(typedArray, options) {
	const { size = 1, startIndex = 0 } = options;
	const endIndex = options.endIndex !== void 0 ? options.endIndex : typedArray.length;
	const count = (endIndex - startIndex) / size;
	scratchArray = typed_array_manager_default.allocate(scratchArray, count, {
		type: Float32Array,
		size: size * 2
	});
	let sourceIndex = startIndex;
	let targetIndex = 0;
	while (sourceIndex < endIndex) {
		for (let j = 0; j < size; j++) {
			const value = typedArray[sourceIndex++];
			scratchArray[targetIndex + j] = value;
			scratchArray[targetIndex + j + size] = fp64LowPart(value);
		}
		targetIndex += size * 2;
	}
	return scratchArray.subarray(0, count * size * 2);
}
function mergeBounds(boundsList) {
	let mergedBounds = null;
	let isMerged = false;
	for (const bounds of boundsList) {
		if (!bounds) continue;
		if (!mergedBounds) mergedBounds = bounds;
		else {
			if (!isMerged) {
				mergedBounds = [[mergedBounds[0][0], mergedBounds[0][1]], [mergedBounds[1][0], mergedBounds[1][1]]];
				isMerged = true;
			}
			mergedBounds[0][0] = Math.min(mergedBounds[0][0], bounds[0][0]);
			mergedBounds[0][1] = Math.min(mergedBounds[0][1], bounds[0][1]);
			mergedBounds[1][0] = Math.max(mergedBounds[1][0], bounds[1][0]);
			mergedBounds[1][1] = Math.max(mergedBounds[1][1], bounds[1][1]);
		}
	}
	return mergedBounds;
}
//#endregion
//#region node_modules/@deck.gl/core/dist/viewports/viewport.js
var DEGREES_TO_RADIANS = Math.PI / 180;
var IDENTITY = createMat4();
var ZERO_VECTOR = [
	0,
	0,
	0
];
var DEFAULT_DISTANCE_SCALES = {
	unitsPerMeter: [
		1,
		1,
		1
	],
	metersPerUnit: [
		1,
		1,
		1
	]
};
function createProjectionMatrix({ width, height, orthographic, fovyRadians, focalDistance, padding, near, far }) {
	const aspect = width / height;
	const matrix = orthographic ? new Matrix4().orthographic({
		fovy: fovyRadians,
		aspect,
		focalDistance,
		near,
		far
	}) : new Matrix4().perspective({
		fovy: fovyRadians,
		aspect,
		near,
		far
	});
	if (padding) {
		const { left = 0, right = 0, top = 0, bottom = 0 } = padding;
		const offsetX = clamp$1((left + width - right) / 2, 0, width) - width / 2;
		const offsetY = clamp$1((top + height - bottom) / 2, 0, height) - height / 2;
		matrix[8] -= offsetX * 2 / width;
		matrix[9] += offsetY * 2 / height;
	}
	return matrix;
}
/**
* Manages coordinate system transformations.
*
* Note: The Viewport is immutable in the sense that it only has accessors.
* A new viewport instance should be created if any parameters have changed.
*/
var Viewport = class Viewport {
	constructor(opts = {}) {
		this._frustumPlanes = {};
		this.id = opts.id || this.constructor.displayName || "viewport";
		this.x = opts.x || 0;
		this.y = opts.y || 0;
		this.width = opts.width || 1;
		this.height = opts.height || 1;
		this.zoom = opts.zoom || 0;
		this.padding = opts.padding;
		this.distanceScales = opts.distanceScales || DEFAULT_DISTANCE_SCALES;
		this.focalDistance = opts.focalDistance || 1;
		this.position = opts.position || ZERO_VECTOR;
		this.modelMatrix = opts.modelMatrix || null;
		const { longitude, latitude } = opts;
		this.isGeospatial = Number.isFinite(latitude) && Number.isFinite(longitude);
		this._initProps(opts);
		this._initMatrices(opts);
		this.equals = this.equals.bind(this);
		this.project = this.project.bind(this);
		this.unproject = this.unproject.bind(this);
		this.projectPosition = this.projectPosition.bind(this);
		this.unprojectPosition = this.unprojectPosition.bind(this);
		this.projectFlat = this.projectFlat.bind(this);
		this.unprojectFlat = this.unprojectFlat.bind(this);
	}
	get subViewports() {
		return null;
	}
	get metersPerPixel() {
		return this.distanceScales.metersPerUnit[2] / this.scale;
	}
	get projectionMode() {
		if (this.isGeospatial) return this.zoom < 12 ? PROJECTION_MODE.WEB_MERCATOR : PROJECTION_MODE.WEB_MERCATOR_AUTO_OFFSET;
		return PROJECTION_MODE.IDENTITY;
	}
	equals(viewport) {
		if (!(viewport instanceof Viewport)) return false;
		if (this === viewport) return true;
		return viewport.width === this.width && viewport.height === this.height && viewport.scale === this.scale && equals(viewport.projectionMatrix, this.projectionMatrix) && equals(viewport.viewMatrix, this.viewMatrix);
	}
	/**
	* Projects xyz (possibly latitude and longitude) to pixel coordinates in window
	* using viewport projection parameters
	* - [longitude, latitude] to [x, y]
	* - [longitude, latitude, Z] => [x, y, z]
	* Note: By default, returns top-left coordinates for canvas/SVG type render
	*
	* @param {Array} lngLatZ - [lng, lat] or [lng, lat, Z]
	* @param {Object} opts - options
	* @param {Object} opts.topLeft=true - Whether projected coords are top left
	* @return {Array} - [x, y] or [x, y, z] in top left coords
	*/
	project(xyz, { topLeft = true } = {}) {
		const coord = worldToPixels(this.projectPosition(xyz), this.pixelProjectionMatrix);
		const [x, y] = coord;
		const y2 = topLeft ? y : this.height - y;
		return xyz.length === 2 ? [x, y2] : [
			x,
			y2,
			coord[2]
		];
	}
	/**
	* Unproject pixel coordinates on screen onto world coordinates,
	* (possibly [lon, lat]) on map.
	* - [x, y] => [lng, lat]
	* - [x, y, z] => [lng, lat, Z]
	* @param {Array} xyz -
	* @param {Object} opts - options
	* @param {Object} opts.topLeft=true - Whether origin is top left
	* @return {Array|null} - [lng, lat, Z] or [X, Y, Z]
	*/
	unproject(xyz, { topLeft = true, targetZ } = {}) {
		const [x, y, z] = xyz;
		const y2 = topLeft ? y : this.height - y;
		const targetZWorld = targetZ && targetZ * this.distanceScales.unitsPerMeter[2];
		const coord = pixelsToWorld([
			x,
			y2,
			z
		], this.pixelUnprojectionMatrix, targetZWorld);
		const [X, Y, Z] = this.unprojectPosition(coord);
		if (Number.isFinite(z)) return [
			X,
			Y,
			Z
		];
		return Number.isFinite(targetZ) ? [
			X,
			Y,
			targetZ
		] : [X, Y];
	}
	projectPosition(xyz) {
		const [X, Y] = this.projectFlat(xyz);
		return [
			X,
			Y,
			(xyz[2] || 0) * this.distanceScales.unitsPerMeter[2]
		];
	}
	unprojectPosition(xyz) {
		const [X, Y] = this.unprojectFlat(xyz);
		return [
			X,
			Y,
			(xyz[2] || 0) * this.distanceScales.metersPerUnit[2]
		];
	}
	/**
	* Project [lng,lat] on sphere onto [x,y] on 512*512 Mercator Zoom 0 tile.
	* Performs the nonlinear part of the web mercator projection.
	* Remaining projection is done with 4x4 matrices which also handles
	* perspective.
	* @param {Array} lngLat - [lng, lat] coordinates
	*   Specifies a point on the sphere to project onto the map.
	* @return {Array} [x,y] coordinates.
	*/
	projectFlat(xyz) {
		if (this.isGeospatial) {
			const result = lngLatToWorld(xyz);
			result[1] = clamp$1(result[1], -318, 830);
			return result;
		}
		return xyz;
	}
	/**
	* Unproject world point [x,y] on map onto {lat, lon} on sphere
	* @param {object|Vector} xy - object with {x,y} members
	*  representing point on projected map plane
	* @return {GeoCoordinates} - object with {lat,lon} of point on sphere.
	*   Has toArray method if you need a GeoJSON Array.
	*   Per cartographic tradition, lat and lon are specified as degrees.
	*/
	unprojectFlat(xyz) {
		if (this.isGeospatial) return worldToLngLat(xyz);
		return xyz;
	}
	/**
	* Get bounds of the current viewport
	* @return {Array} - [minX, minY, maxX, maxY]
	*/
	getBounds(options = {}) {
		const unprojectOption = { targetZ: options.z || 0 };
		const topLeft = this.unproject([0, 0], unprojectOption);
		const topRight = this.unproject([this.width, 0], unprojectOption);
		const bottomLeft = this.unproject([0, this.height], unprojectOption);
		const bottomRight = this.unproject([this.width, this.height], unprojectOption);
		return [
			Math.min(topLeft[0], topRight[0], bottomLeft[0], bottomRight[0]),
			Math.min(topLeft[1], topRight[1], bottomLeft[1], bottomRight[1]),
			Math.max(topLeft[0], topRight[0], bottomLeft[0], bottomRight[0]),
			Math.max(topLeft[1], topRight[1], bottomLeft[1], bottomRight[1])
		];
	}
	getDistanceScales(coordinateOrigin) {
		if (coordinateOrigin && this.isGeospatial) return getDistanceScales({
			longitude: coordinateOrigin[0],
			latitude: coordinateOrigin[1],
			highPrecision: true
		});
		return this.distanceScales;
	}
	containsPixel({ x, y, width = 1, height = 1 }) {
		return x < this.x + this.width && this.x < x + width && y < this.y + this.height && this.y < y + height;
	}
	getFrustumPlanes() {
		if (this._frustumPlanes.near) return this._frustumPlanes;
		Object.assign(this._frustumPlanes, getFrustumPlanes(this.viewProjectionMatrix));
		return this._frustumPlanes;
	}
	/**
	* Needed by panning and linear transition
	* Pan the viewport to place a given world coordinate at screen point [x, y]
	*
	* @param {Array} coords - world coordinates
	* @param {Array} pixel - [x,y] coordinates on screen
	* @param {Array} startPixel - [x,y] screen position where pan started (optional, for delta-based panning)
	* @return {Object} props of the new viewport
	*/
	panByPosition(coords, pixel, startPixel) {
		return null;
	}
	_initProps(opts) {
		const longitude = opts.longitude;
		const latitude = opts.latitude;
		if (this.isGeospatial) {
			if (!Number.isFinite(opts.zoom)) this.zoom = getMeterZoom({ latitude }) + Math.log2(this.focalDistance);
			this.distanceScales = opts.distanceScales || getDistanceScales({
				latitude,
				longitude
			});
		}
		const scale = Math.pow(2, this.zoom);
		this.scale = scale;
		const { position, modelMatrix } = opts;
		let meterOffset = ZERO_VECTOR;
		if (position) meterOffset = modelMatrix ? new Matrix4(modelMatrix).transformAsVector(position, []) : position;
		if (this.isGeospatial) {
			const center = this.projectPosition([
				longitude,
				latitude,
				0
			]);
			this.center = new Vector3(meterOffset).scale(this.distanceScales.unitsPerMeter).add(center);
		} else this.center = this.projectPosition(meterOffset);
	}
	_initMatrices(opts) {
		const { viewMatrix = IDENTITY, projectionMatrix = null, orthographic = false, fovyRadians, fovy = 75, near = .1, far = 1e3, padding = null, focalDistance = 1 } = opts;
		this.viewMatrixUncentered = viewMatrix;
		this.viewMatrix = new Matrix4().multiplyRight(viewMatrix).translate(new Vector3(this.center).negate());
		this.projectionMatrix = projectionMatrix || createProjectionMatrix({
			width: this.width,
			height: this.height,
			orthographic,
			fovyRadians: fovyRadians || fovy * DEGREES_TO_RADIANS,
			focalDistance,
			padding,
			near,
			far
		});
		const vpm = createMat4();
		multiply(vpm, vpm, this.projectionMatrix);
		multiply(vpm, vpm, this.viewMatrix);
		this.viewProjectionMatrix = vpm;
		this.viewMatrixInverse = invert([], this.viewMatrix) || this.viewMatrix;
		this.cameraPosition = getCameraPosition(this.viewMatrixInverse);
		const viewportMatrix = createMat4();
		const pixelProjectionMatrix = createMat4();
		scale$1(viewportMatrix, viewportMatrix, [
			this.width / 2,
			-this.height / 2,
			1
		]);
		translate(viewportMatrix, viewportMatrix, [
			1,
			-1,
			0
		]);
		multiply(pixelProjectionMatrix, viewportMatrix, this.viewProjectionMatrix);
		this.pixelProjectionMatrix = pixelProjectionMatrix;
		this.pixelUnprojectionMatrix = invert(createMat4(), this.pixelProjectionMatrix);
		if (!this.pixelUnprojectionMatrix) defaultLogger.warn("Pixel project matrix not invertible")();
	}
};
Viewport.displayName = "Viewport";
//#endregion
//#region node_modules/@deck.gl/core/dist/viewports/web-mercator-viewport.js
/**
* Manages transformations to/from WGS84 coordinates using the Web Mercator Projection.
*/
var WebMercatorViewport = class WebMercatorViewport extends Viewport {
	constructor(opts = {}) {
		const { latitude = 0, longitude = 0, zoom = 0, pitch = 0, bearing = 0, nearZMultiplier = .1, farZMultiplier = 1.01, nearZ, farZ, orthographic = false, projectionMatrix, repeat = false, worldOffset = 0, position, padding, legacyMeterSizes = false } = opts;
		let { width, height, altitude = 1.5 } = opts;
		const scale = Math.pow(2, zoom);
		width = width || 1;
		height = height || 1;
		let fovy;
		let projectionParameters = null;
		if (projectionMatrix) {
			altitude = projectionMatrix[5] / 2;
			fovy = altitudeToFovy(altitude);
		} else {
			if (opts.fovy) {
				fovy = opts.fovy;
				altitude = fovyToAltitude(fovy);
			} else fovy = altitudeToFovy(altitude);
			let offset;
			if (padding) {
				const { top = 0, bottom = 0 } = padding;
				offset = [0, clamp$1((top + height - bottom) / 2, 0, height) - height / 2];
			}
			projectionParameters = getProjectionParameters({
				width,
				height,
				scale,
				center: position && [
					0,
					0,
					position[2] * unitsPerMeter(latitude)
				],
				offset,
				pitch,
				fovy,
				nearZMultiplier,
				farZMultiplier
			});
			if (Number.isFinite(nearZ)) projectionParameters.near = nearZ;
			if (Number.isFinite(farZ)) projectionParameters.far = farZ;
		}
		let viewMatrixUncentered = getViewMatrix({
			height,
			pitch,
			bearing,
			scale,
			altitude
		});
		if (worldOffset) viewMatrixUncentered = new Matrix4().translate([
			512 * worldOffset,
			0,
			0
		]).multiplyLeft(viewMatrixUncentered);
		super({
			...opts,
			width,
			height,
			viewMatrix: viewMatrixUncentered,
			longitude,
			latitude,
			zoom,
			...projectionParameters,
			fovy,
			focalDistance: altitude
		});
		this.latitude = latitude;
		this.longitude = longitude;
		this.zoom = zoom;
		this.pitch = pitch;
		this.bearing = bearing;
		this.altitude = altitude;
		this.fovy = fovy;
		this.orthographic = orthographic;
		this._subViewports = repeat ? [] : null;
		this._pseudoMeters = legacyMeterSizes;
		Object.freeze(this);
	}
	get subViewports() {
		if (this._subViewports && !this._subViewports.length) {
			const bounds = this.getBounds();
			const minOffset = Math.floor((bounds[0] + 180) / 360);
			const maxOffset = Math.ceil((bounds[2] - 180) / 360);
			for (let x = minOffset; x <= maxOffset; x++) {
				const offsetViewport = x ? new WebMercatorViewport({
					...this,
					worldOffset: x
				}) : this;
				this._subViewports.push(offsetViewport);
			}
		}
		return this._subViewports;
	}
	projectPosition(xyz) {
		if (this._pseudoMeters) return super.projectPosition(xyz);
		const [X, Y] = this.projectFlat(xyz);
		return [
			X,
			Y,
			(xyz[2] || 0) * unitsPerMeter(xyz[1])
		];
	}
	unprojectPosition(xyz) {
		if (this._pseudoMeters) return super.unprojectPosition(xyz);
		const [X, Y] = this.unprojectFlat(xyz);
		return [
			X,
			Y,
			(xyz[2] || 0) / unitsPerMeter(Y)
		];
	}
	/**
	* Add a meter delta to a base lnglat coordinate, returning a new lnglat array
	*
	* Note: Uses simple linear approximation around the viewport center
	* Error increases with size of offset (roughly 1% per 100km)
	*
	* @param {[Number,Number]|[Number,Number,Number]) lngLatZ - base coordinate
	* @param {[Number,Number]|[Number,Number,Number]) xyz - array of meter deltas
	* @return {[Number,Number]|[Number,Number,Number]) array of [lng,lat,z] deltas
	*/
	addMetersToLngLat(lngLatZ, xyz) {
		return addMetersToLngLat(lngLatZ, xyz);
	}
	panByPosition(coords, pixel, startPixel) {
		const fromLocation = pixelsToWorld(pixel, this.pixelUnprojectionMatrix);
		const translate = add([], this.projectFlat(coords), negate$1([], fromLocation));
		const newCenter = add([], this.center, translate);
		const [longitude, latitude] = this.unprojectFlat(newCenter);
		return {
			longitude,
			latitude
		};
	}
	/**
	* Returns a new longitude and latitude that keeps a 3D world coordinate at a given screen pixel
	* This version handles the z-component (altitude) properly for cameras positioned above ground
	*/
	panByPosition3D(coords, pixel) {
		const targetZ = coords[2] || 0;
		const deltaLngLat = sub$1([], coords, this.unproject(pixel, { targetZ }));
		return {
			longitude: this.longitude + deltaLngLat[0],
			latitude: this.latitude + deltaLngLat[1]
		};
	}
	getBounds(options = {}) {
		const corners = getBounds(this, options.z || 0);
		return [
			Math.min(corners[0][0], corners[1][0], corners[2][0], corners[3][0]),
			Math.min(corners[0][1], corners[1][1], corners[2][1], corners[3][1]),
			Math.max(corners[0][0], corners[1][0], corners[2][0], corners[3][0]),
			Math.max(corners[0][1], corners[1][1], corners[2][1], corners[3][1])
		];
	}
	/**
	* Returns a new viewport that fit around the given rectangle.
	* Only supports non-perspective mode.
	*/
	fitBounds(bounds, options = {}) {
		const { width, height } = this;
		const { longitude, latitude, zoom } = fitBounds({
			width,
			height,
			bounds,
			...options
		});
		return new WebMercatorViewport({
			width,
			height,
			longitude,
			latitude,
			zoom
		});
	}
};
WebMercatorViewport.displayName = "WebMercatorViewport";
//#endregion
//#region node_modules/@deck.gl/core/dist/lifecycle/constants.js
var LIFECYCLE = {
	NO_STATE: "Awaiting state",
	MATCHED: "Matched. State transferred from previous layer",
	INITIALIZED: "Initialized",
	AWAITING_GC: "Discarded. Awaiting garbage collection",
	AWAITING_FINALIZATION: "No longer matched. Awaiting garbage collection",
	FINALIZED: "Finalized! Awaiting garbage collection"
};
var COMPONENT_SYMBOL = Symbol.for("component");
var PROP_TYPES_SYMBOL = Symbol.for("propTypes");
var DEPRECATED_PROPS_SYMBOL = Symbol.for("deprecatedProps");
var ASYNC_DEFAULTS_SYMBOL = Symbol.for("asyncPropDefaults");
var ASYNC_ORIGINAL_SYMBOL = Symbol.for("asyncPropOriginal");
var ASYNC_RESOLVED_SYMBOL = Symbol.for("asyncPropResolved");
//#endregion
//#region node_modules/@deck.gl/core/dist/utils/flatten.js
/**
* Flattens a nested array into a single level array,
* or a single value into an array with one value
* @example flatten([[1, [2]], [3], 4]) => [1, 2, 3, 4]
* @example flatten(1) => [1]
* @param array The array to flatten.
* @param filter= - Optional predicate called on each `value` to
*   determine if it should be included (pushed onto) the resulting array.
* @return Returns the new flattened array (new array or `result` if provided)
*/
function flatten(array, filter = () => true) {
	if (!Array.isArray(array)) return filter(array) ? [array] : [];
	return flattenArray(array, filter, []);
}
/** Deep flattens an array. Helper to `flatten`, see its parameters */
function flattenArray(array, filter, result) {
	let index = -1;
	while (++index < array.length) {
		const value = array[index];
		if (Array.isArray(value)) flattenArray(value, filter, result);
		else if (filter(value)) result.push(value);
	}
	return result;
}
/** Uses copyWithin to significantly speed up typed array value filling */
function fillArray({ target, source, start = 0, count = 1 }) {
	const length = source.length;
	const total = count * length;
	let copied = 0;
	for (let i = start; copied < length; copied++) target[i++] = source[copied];
	while (copied < total) if (copied < total - copied) {
		target.copyWithin(start + copied, start, start + copied);
		copied *= 2;
	} else {
		target.copyWithin(start + copied, start, start + total - copied);
		copied = total;
	}
	return target;
}
//#endregion
//#region node_modules/@deck.gl/core/dist/utils/deep-equal.js
/**
* Fast partial deep equal for prop.
*
* @param a Prop
* @param b Prop to compare against `a`
* @param depth Depth to which to recurse in nested Objects/Arrays. Use 0 (default) for shallow comparison, -1 for infinite depth
*/
function deepEqual(a, b, depth) {
	if (a === b) return true;
	if (!depth || !a || !b) return false;
	if (Array.isArray(a)) {
		if (!Array.isArray(b) || a.length !== b.length) return false;
		for (let i = 0; i < a.length; i++) if (!deepEqual(a[i], b[i], depth - 1)) return false;
		return true;
	}
	if (Array.isArray(b)) return false;
	if (typeof a === "object" && typeof b === "object") {
		const aKeys = Object.keys(a);
		const bKeys = Object.keys(b);
		if (aKeys.length !== bKeys.length) return false;
		for (const key of aKeys) {
			if (!b.hasOwnProperty(key)) return false;
			if (!deepEqual(a[key], b[key], depth - 1)) return false;
		}
		return true;
	}
	return false;
}
//#endregion
//#region node_modules/@deck.gl/core/dist/transitions/transition.js
var Transition = class {
	/**
	* @params timeline {Timeline}
	*/
	constructor(timeline) {
		this._inProgress = false;
		this._handle = null;
		this.time = 0;
		this.settings = { duration: 0 };
		this._timeline = timeline;
	}
	get inProgress() {
		return this._inProgress;
	}
	/**
	* (re)start this transition.
	* @params props {object} - optional overriding props. see constructor
	*/
	start(settings) {
		this.cancel();
		this.settings = settings;
		this._inProgress = true;
		this.settings.onStart?.(this);
	}
	/**
	* end this transition if it is in progress.
	*/
	end() {
		if (this._inProgress) {
			this._timeline.removeChannel(this._handle);
			this._handle = null;
			this._inProgress = false;
			this.settings.onEnd?.(this);
		}
	}
	/**
	* cancel this transition if it is in progress.
	*/
	cancel() {
		if (this._inProgress) {
			this.settings.onInterrupt?.(this);
			this._timeline.removeChannel(this._handle);
			this._handle = null;
			this._inProgress = false;
		}
	}
	/**
	* update this transition. Returns `true` if updated.
	*/
	update() {
		if (!this._inProgress) return false;
		if (this._handle === null) {
			const { _timeline: timeline, settings } = this;
			this._handle = timeline.addChannel({
				delay: timeline.getTime(),
				duration: settings.duration
			});
		}
		this.time = this._timeline.getTime(this._handle);
		this._onUpdate();
		this.settings.onUpdate?.(this);
		if (this._timeline.isFinished(this._handle)) this.end();
		return true;
	}
	_onUpdate() {}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/utils/assert.js
function assert(condition, message) {
	if (!condition) throw new Error(message || "deck.gl: assertion failed.");
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/constants/webgl-constants.js
/**
* Standard WebGL, WebGL2 and extension constants (OpenGL constants)
* @note (Most) of these constants are also defined on the WebGLRenderingContext interface.
* @see https://developer.mozilla.org/en-US/docs/Web/API/WebGL_API/Constants
* @privateRemarks Locally called `GLEnum` instead of `GL`, because `babel-plugin-inline-webl-constants`
*  both depends on and processes this module, but shouldn't replace these declarations.
*/
var GLEnum;
(function(GLEnum) {
	/** Passed to clear to clear the current depth buffer. */
	GLEnum[GLEnum["DEPTH_BUFFER_BIT"] = 256] = "DEPTH_BUFFER_BIT";
	/** Passed to clear to clear the current stencil buffer. */
	GLEnum[GLEnum["STENCIL_BUFFER_BIT"] = 1024] = "STENCIL_BUFFER_BIT";
	/** Passed to clear to clear the current color buffer. */
	GLEnum[GLEnum["COLOR_BUFFER_BIT"] = 16384] = "COLOR_BUFFER_BIT";
	/** Passed to drawElements or drawArrays to draw single points. */
	GLEnum[GLEnum["POINTS"] = 0] = "POINTS";
	/** Passed to drawElements or drawArrays to draw lines. Each vertex connects to the one after it. */
	GLEnum[GLEnum["LINES"] = 1] = "LINES";
	/** Passed to drawElements or drawArrays to draw lines. Each set of two vertices is treated as a separate line segment. */
	GLEnum[GLEnum["LINE_LOOP"] = 2] = "LINE_LOOP";
	/** Passed to drawElements or drawArrays to draw a connected group of line segments from the first vertex to the last. */
	GLEnum[GLEnum["LINE_STRIP"] = 3] = "LINE_STRIP";
	/** Passed to drawElements or drawArrays to draw triangles. Each set of three vertices creates a separate triangle. */
	GLEnum[GLEnum["TRIANGLES"] = 4] = "TRIANGLES";
	/** Passed to drawElements or drawArrays to draw a connected group of triangles. */
	GLEnum[GLEnum["TRIANGLE_STRIP"] = 5] = "TRIANGLE_STRIP";
	/** Passed to drawElements or drawArrays to draw a connected group of triangles. Each vertex connects to the previous and the first vertex in the fan. */
	GLEnum[GLEnum["TRIANGLE_FAN"] = 6] = "TRIANGLE_FAN";
	/** Passed to blendFunc or blendFuncSeparate to turn off a component. */
	GLEnum[GLEnum["ZERO"] = 0] = "ZERO";
	/** Passed to blendFunc or blendFuncSeparate to turn on a component. */
	GLEnum[GLEnum["ONE"] = 1] = "ONE";
	/** Passed to blendFunc or blendFuncSeparate to multiply a component by the source elements color. */
	GLEnum[GLEnum["SRC_COLOR"] = 768] = "SRC_COLOR";
	/** Passed to blendFunc or blendFuncSeparate to multiply a component by one minus the source elements color. */
	GLEnum[GLEnum["ONE_MINUS_SRC_COLOR"] = 769] = "ONE_MINUS_SRC_COLOR";
	/** Passed to blendFunc or blendFuncSeparate to multiply a component by the source's alpha. */
	GLEnum[GLEnum["SRC_ALPHA"] = 770] = "SRC_ALPHA";
	/** Passed to blendFunc or blendFuncSeparate to multiply a component by one minus the source's alpha. */
	GLEnum[GLEnum["ONE_MINUS_SRC_ALPHA"] = 771] = "ONE_MINUS_SRC_ALPHA";
	/** Passed to blendFunc or blendFuncSeparate to multiply a component by the destination's alpha. */
	GLEnum[GLEnum["DST_ALPHA"] = 772] = "DST_ALPHA";
	/** Passed to blendFunc or blendFuncSeparate to multiply a component by one minus the destination's alpha. */
	GLEnum[GLEnum["ONE_MINUS_DST_ALPHA"] = 773] = "ONE_MINUS_DST_ALPHA";
	/** Passed to blendFunc or blendFuncSeparate to multiply a component by the destination's color. */
	GLEnum[GLEnum["DST_COLOR"] = 774] = "DST_COLOR";
	/** Passed to blendFunc or blendFuncSeparate to multiply a component by one minus the destination's color. */
	GLEnum[GLEnum["ONE_MINUS_DST_COLOR"] = 775] = "ONE_MINUS_DST_COLOR";
	/** Passed to blendFunc or blendFuncSeparate to multiply a component by the minimum of source's alpha or one minus the destination's alpha. */
	GLEnum[GLEnum["SRC_ALPHA_SATURATE"] = 776] = "SRC_ALPHA_SATURATE";
	/** Passed to blendFunc or blendFuncSeparate to specify a constant color blend function. */
	GLEnum[GLEnum["CONSTANT_COLOR"] = 32769] = "CONSTANT_COLOR";
	/** Passed to blendFunc or blendFuncSeparate to specify one minus a constant color blend function. */
	GLEnum[GLEnum["ONE_MINUS_CONSTANT_COLOR"] = 32770] = "ONE_MINUS_CONSTANT_COLOR";
	/** Passed to blendFunc or blendFuncSeparate to specify a constant alpha blend function. */
	GLEnum[GLEnum["CONSTANT_ALPHA"] = 32771] = "CONSTANT_ALPHA";
	/** Passed to blendFunc or blendFuncSeparate to specify one minus a constant alpha blend function. */
	GLEnum[GLEnum["ONE_MINUS_CONSTANT_ALPHA"] = 32772] = "ONE_MINUS_CONSTANT_ALPHA";
	/** Passed to blendEquation or blendEquationSeparate to set an addition blend function. */
	/** Passed to blendEquation or blendEquationSeparate to specify a subtraction blend function (source - destination). */
	/** Passed to blendEquation or blendEquationSeparate to specify a reverse subtraction blend function (destination - source). */
	GLEnum[GLEnum["FUNC_ADD"] = 32774] = "FUNC_ADD";
	GLEnum[GLEnum["FUNC_SUBTRACT"] = 32778] = "FUNC_SUBTRACT";
	GLEnum[GLEnum["FUNC_REVERSE_SUBTRACT"] = 32779] = "FUNC_REVERSE_SUBTRACT";
	/** Passed to getParameter to get the current RGB blend function. */
	GLEnum[GLEnum["BLEND_EQUATION"] = 32777] = "BLEND_EQUATION";
	/** Passed to getParameter to get the current RGB blend function. Same as BLEND_EQUATION */
	GLEnum[GLEnum["BLEND_EQUATION_RGB"] = 32777] = "BLEND_EQUATION_RGB";
	/** Passed to getParameter to get the current alpha blend function. Same as BLEND_EQUATION */
	GLEnum[GLEnum["BLEND_EQUATION_ALPHA"] = 34877] = "BLEND_EQUATION_ALPHA";
	/** Passed to getParameter to get the current destination RGB blend function. */
	GLEnum[GLEnum["BLEND_DST_RGB"] = 32968] = "BLEND_DST_RGB";
	/** Passed to getParameter to get the current destination RGB blend function. */
	GLEnum[GLEnum["BLEND_SRC_RGB"] = 32969] = "BLEND_SRC_RGB";
	/** Passed to getParameter to get the current destination alpha blend function. */
	GLEnum[GLEnum["BLEND_DST_ALPHA"] = 32970] = "BLEND_DST_ALPHA";
	/** Passed to getParameter to get the current source alpha blend function. */
	GLEnum[GLEnum["BLEND_SRC_ALPHA"] = 32971] = "BLEND_SRC_ALPHA";
	/** Passed to getParameter to return a the current blend color. */
	GLEnum[GLEnum["BLEND_COLOR"] = 32773] = "BLEND_COLOR";
	/** Passed to getParameter to get the array buffer binding. */
	GLEnum[GLEnum["ARRAY_BUFFER_BINDING"] = 34964] = "ARRAY_BUFFER_BINDING";
	/** Passed to getParameter to get the current element array buffer. */
	GLEnum[GLEnum["ELEMENT_ARRAY_BUFFER_BINDING"] = 34965] = "ELEMENT_ARRAY_BUFFER_BINDING";
	/** Passed to getParameter to get the current lineWidth (set by the lineWidth method). */
	GLEnum[GLEnum["LINE_WIDTH"] = 2849] = "LINE_WIDTH";
	/** Passed to getParameter to get the current size of a point drawn with gl.POINTS */
	GLEnum[GLEnum["ALIASED_POINT_SIZE_RANGE"] = 33901] = "ALIASED_POINT_SIZE_RANGE";
	/** Passed to getParameter to get the range of available widths for a line. Returns a length-2 array with the lo value at 0, and hight at 1. */
	GLEnum[GLEnum["ALIASED_LINE_WIDTH_RANGE"] = 33902] = "ALIASED_LINE_WIDTH_RANGE";
	/** Passed to getParameter to get the current value of cullFace. Should return FRONT, BACK, or FRONT_AND_BACK */
	GLEnum[GLEnum["CULL_FACE_MODE"] = 2885] = "CULL_FACE_MODE";
	/** Passed to getParameter to determine the current value of frontFace. Should return CW or CCW. */
	GLEnum[GLEnum["FRONT_FACE"] = 2886] = "FRONT_FACE";
	/** Passed to getParameter to return a length-2 array of floats giving the current depth range. */
	GLEnum[GLEnum["DEPTH_RANGE"] = 2928] = "DEPTH_RANGE";
	/** Passed to getParameter to determine if the depth write mask is enabled. */
	GLEnum[GLEnum["DEPTH_WRITEMASK"] = 2930] = "DEPTH_WRITEMASK";
	/** Passed to getParameter to determine the current depth clear value. */
	GLEnum[GLEnum["DEPTH_CLEAR_VALUE"] = 2931] = "DEPTH_CLEAR_VALUE";
	/** Passed to getParameter to get the current depth function. Returns NEVER, ALWAYS, LESS, EQUAL, LEQUAL, GREATER, GEQUAL, or NOTEQUAL. */
	GLEnum[GLEnum["DEPTH_FUNC"] = 2932] = "DEPTH_FUNC";
	/** Passed to getParameter to get the value the stencil will be cleared to. */
	GLEnum[GLEnum["STENCIL_CLEAR_VALUE"] = 2961] = "STENCIL_CLEAR_VALUE";
	/** Passed to getParameter to get the current stencil function. Returns NEVER, ALWAYS, LESS, EQUAL, LEQUAL, GREATER, GEQUAL, or NOTEQUAL. */
	GLEnum[GLEnum["STENCIL_FUNC"] = 2962] = "STENCIL_FUNC";
	/** Passed to getParameter to get the current stencil fail function. Should return KEEP, REPLACE, INCR, DECR, INVERT, INCR_WRAP, or DECR_WRAP. */
	GLEnum[GLEnum["STENCIL_FAIL"] = 2964] = "STENCIL_FAIL";
	/** Passed to getParameter to get the current stencil fail function should the depth buffer test fail. Should return KEEP, REPLACE, INCR, DECR, INVERT, INCR_WRAP, or DECR_WRAP. */
	GLEnum[GLEnum["STENCIL_PASS_DEPTH_FAIL"] = 2965] = "STENCIL_PASS_DEPTH_FAIL";
	/** Passed to getParameter to get the current stencil fail function should the depth buffer test pass. Should return KEEP, REPLACE, INCR, DECR, INVERT, INCR_WRAP, or DECR_WRAP. */
	GLEnum[GLEnum["STENCIL_PASS_DEPTH_PASS"] = 2966] = "STENCIL_PASS_DEPTH_PASS";
	/** Passed to getParameter to get the reference value used for stencil tests. */
	GLEnum[GLEnum["STENCIL_REF"] = 2967] = "STENCIL_REF";
	GLEnum[GLEnum["STENCIL_VALUE_MASK"] = 2963] = "STENCIL_VALUE_MASK";
	GLEnum[GLEnum["STENCIL_WRITEMASK"] = 2968] = "STENCIL_WRITEMASK";
	GLEnum[GLEnum["STENCIL_BACK_FUNC"] = 34816] = "STENCIL_BACK_FUNC";
	GLEnum[GLEnum["STENCIL_BACK_FAIL"] = 34817] = "STENCIL_BACK_FAIL";
	GLEnum[GLEnum["STENCIL_BACK_PASS_DEPTH_FAIL"] = 34818] = "STENCIL_BACK_PASS_DEPTH_FAIL";
	GLEnum[GLEnum["STENCIL_BACK_PASS_DEPTH_PASS"] = 34819] = "STENCIL_BACK_PASS_DEPTH_PASS";
	GLEnum[GLEnum["STENCIL_BACK_REF"] = 36003] = "STENCIL_BACK_REF";
	GLEnum[GLEnum["STENCIL_BACK_VALUE_MASK"] = 36004] = "STENCIL_BACK_VALUE_MASK";
	GLEnum[GLEnum["STENCIL_BACK_WRITEMASK"] = 36005] = "STENCIL_BACK_WRITEMASK";
	/** An Int32Array with four elements for the current viewport dimensions. */
	GLEnum[GLEnum["VIEWPORT"] = 2978] = "VIEWPORT";
	/** An Int32Array with four elements for the current scissor box dimensions. */
	GLEnum[GLEnum["SCISSOR_BOX"] = 3088] = "SCISSOR_BOX";
	GLEnum[GLEnum["COLOR_CLEAR_VALUE"] = 3106] = "COLOR_CLEAR_VALUE";
	GLEnum[GLEnum["COLOR_WRITEMASK"] = 3107] = "COLOR_WRITEMASK";
	GLEnum[GLEnum["UNPACK_ALIGNMENT"] = 3317] = "UNPACK_ALIGNMENT";
	GLEnum[GLEnum["PACK_ALIGNMENT"] = 3333] = "PACK_ALIGNMENT";
	GLEnum[GLEnum["MAX_TEXTURE_SIZE"] = 3379] = "MAX_TEXTURE_SIZE";
	GLEnum[GLEnum["MAX_VIEWPORT_DIMS"] = 3386] = "MAX_VIEWPORT_DIMS";
	GLEnum[GLEnum["SUBPIXEL_BITS"] = 3408] = "SUBPIXEL_BITS";
	GLEnum[GLEnum["RED_BITS"] = 3410] = "RED_BITS";
	GLEnum[GLEnum["GREEN_BITS"] = 3411] = "GREEN_BITS";
	GLEnum[GLEnum["BLUE_BITS"] = 3412] = "BLUE_BITS";
	GLEnum[GLEnum["ALPHA_BITS"] = 3413] = "ALPHA_BITS";
	GLEnum[GLEnum["DEPTH_BITS"] = 3414] = "DEPTH_BITS";
	GLEnum[GLEnum["STENCIL_BITS"] = 3415] = "STENCIL_BITS";
	GLEnum[GLEnum["POLYGON_OFFSET_UNITS"] = 10752] = "POLYGON_OFFSET_UNITS";
	GLEnum[GLEnum["POLYGON_OFFSET_FACTOR"] = 32824] = "POLYGON_OFFSET_FACTOR";
	GLEnum[GLEnum["TEXTURE_BINDING_2D"] = 32873] = "TEXTURE_BINDING_2D";
	GLEnum[GLEnum["SAMPLE_BUFFERS"] = 32936] = "SAMPLE_BUFFERS";
	GLEnum[GLEnum["SAMPLES"] = 32937] = "SAMPLES";
	GLEnum[GLEnum["SAMPLE_COVERAGE_VALUE"] = 32938] = "SAMPLE_COVERAGE_VALUE";
	GLEnum[GLEnum["SAMPLE_COVERAGE_INVERT"] = 32939] = "SAMPLE_COVERAGE_INVERT";
	GLEnum[GLEnum["COMPRESSED_TEXTURE_FORMATS"] = 34467] = "COMPRESSED_TEXTURE_FORMATS";
	GLEnum[GLEnum["VENDOR"] = 7936] = "VENDOR";
	GLEnum[GLEnum["RENDERER"] = 7937] = "RENDERER";
	GLEnum[GLEnum["VERSION"] = 7938] = "VERSION";
	GLEnum[GLEnum["IMPLEMENTATION_COLOR_READ_TYPE"] = 35738] = "IMPLEMENTATION_COLOR_READ_TYPE";
	GLEnum[GLEnum["IMPLEMENTATION_COLOR_READ_FORMAT"] = 35739] = "IMPLEMENTATION_COLOR_READ_FORMAT";
	GLEnum[GLEnum["BROWSER_DEFAULT_WEBGL"] = 37444] = "BROWSER_DEFAULT_WEBGL";
	/** Passed to bufferData as a hint about whether the contents of the buffer are likely to be used often and not change often. */
	GLEnum[GLEnum["STATIC_DRAW"] = 35044] = "STATIC_DRAW";
	/** Passed to bufferData as a hint about whether the contents of the buffer are likely to not be used often. */
	GLEnum[GLEnum["STREAM_DRAW"] = 35040] = "STREAM_DRAW";
	/** Passed to bufferData as a hint about whether the contents of the buffer are likely to be used often and change often. */
	GLEnum[GLEnum["DYNAMIC_DRAW"] = 35048] = "DYNAMIC_DRAW";
	/** Passed to bindBuffer or bufferData to specify the type of buffer being used. */
	GLEnum[GLEnum["ARRAY_BUFFER"] = 34962] = "ARRAY_BUFFER";
	/** Passed to bindBuffer or bufferData to specify the type of buffer being used. */
	GLEnum[GLEnum["ELEMENT_ARRAY_BUFFER"] = 34963] = "ELEMENT_ARRAY_BUFFER";
	/** Passed to getBufferParameter to get a buffer's size. */
	GLEnum[GLEnum["BUFFER_SIZE"] = 34660] = "BUFFER_SIZE";
	/** Passed to getBufferParameter to get the hint for the buffer passed in when it was created. */
	GLEnum[GLEnum["BUFFER_USAGE"] = 34661] = "BUFFER_USAGE";
	/** Passed to getVertexAttrib to read back the current vertex attribute. */
	GLEnum[GLEnum["CURRENT_VERTEX_ATTRIB"] = 34342] = "CURRENT_VERTEX_ATTRIB";
	GLEnum[GLEnum["VERTEX_ATTRIB_ARRAY_ENABLED"] = 34338] = "VERTEX_ATTRIB_ARRAY_ENABLED";
	GLEnum[GLEnum["VERTEX_ATTRIB_ARRAY_SIZE"] = 34339] = "VERTEX_ATTRIB_ARRAY_SIZE";
	GLEnum[GLEnum["VERTEX_ATTRIB_ARRAY_STRIDE"] = 34340] = "VERTEX_ATTRIB_ARRAY_STRIDE";
	GLEnum[GLEnum["VERTEX_ATTRIB_ARRAY_TYPE"] = 34341] = "VERTEX_ATTRIB_ARRAY_TYPE";
	GLEnum[GLEnum["VERTEX_ATTRIB_ARRAY_NORMALIZED"] = 34922] = "VERTEX_ATTRIB_ARRAY_NORMALIZED";
	GLEnum[GLEnum["VERTEX_ATTRIB_ARRAY_POINTER"] = 34373] = "VERTEX_ATTRIB_ARRAY_POINTER";
	GLEnum[GLEnum["VERTEX_ATTRIB_ARRAY_BUFFER_BINDING"] = 34975] = "VERTEX_ATTRIB_ARRAY_BUFFER_BINDING";
	/** Passed to enable/disable to turn on/off culling. Can also be used with getParameter to find the current culling method. */
	GLEnum[GLEnum["CULL_FACE"] = 2884] = "CULL_FACE";
	/** Passed to cullFace to specify that only front faces should be culled. */
	GLEnum[GLEnum["FRONT"] = 1028] = "FRONT";
	/** Passed to cullFace to specify that only back faces should be culled. */
	GLEnum[GLEnum["BACK"] = 1029] = "BACK";
	/** Passed to cullFace to specify that front and back faces should be culled. */
	GLEnum[GLEnum["FRONT_AND_BACK"] = 1032] = "FRONT_AND_BACK";
	/** Passed to enable/disable to turn on/off blending. Can also be used with getParameter to find the current blending method. */
	GLEnum[GLEnum["BLEND"] = 3042] = "BLEND";
	/** Passed to enable/disable to turn on/off the depth test. Can also be used with getParameter to query the depth test. */
	GLEnum[GLEnum["DEPTH_TEST"] = 2929] = "DEPTH_TEST";
	/** Passed to enable/disable to turn on/off dithering. Can also be used with getParameter to find the current dithering method. */
	GLEnum[GLEnum["DITHER"] = 3024] = "DITHER";
	/** Passed to enable/disable to turn on/off the polygon offset. Useful for rendering hidden-line images, decals, and or solids with highlighted edges. Can also be used with getParameter to query the scissor test. */
	GLEnum[GLEnum["POLYGON_OFFSET_FILL"] = 32823] = "POLYGON_OFFSET_FILL";
	/** Passed to enable/disable to turn on/off the alpha to coverage. Used in multi-sampling alpha channels. */
	GLEnum[GLEnum["SAMPLE_ALPHA_TO_COVERAGE"] = 32926] = "SAMPLE_ALPHA_TO_COVERAGE";
	/** Passed to enable/disable to turn on/off the sample coverage. Used in multi-sampling. */
	GLEnum[GLEnum["SAMPLE_COVERAGE"] = 32928] = "SAMPLE_COVERAGE";
	/** Passed to enable/disable to turn on/off the scissor test. Can also be used with getParameter to query the scissor test. */
	GLEnum[GLEnum["SCISSOR_TEST"] = 3089] = "SCISSOR_TEST";
	/** Passed to enable/disable to turn on/off the stencil test. Can also be used with getParameter to query the stencil test. */
	GLEnum[GLEnum["STENCIL_TEST"] = 2960] = "STENCIL_TEST";
	/** Returned from getError(). */
	GLEnum[GLEnum["NO_ERROR"] = 0] = "NO_ERROR";
	/** Returned from getError(). */
	GLEnum[GLEnum["INVALID_ENUM"] = 1280] = "INVALID_ENUM";
	/** Returned from getError(). */
	GLEnum[GLEnum["INVALID_VALUE"] = 1281] = "INVALID_VALUE";
	/** Returned from getError(). */
	GLEnum[GLEnum["INVALID_OPERATION"] = 1282] = "INVALID_OPERATION";
	/** Returned from getError(). */
	GLEnum[GLEnum["OUT_OF_MEMORY"] = 1285] = "OUT_OF_MEMORY";
	/** Returned from getError(). */
	GLEnum[GLEnum["CONTEXT_LOST_WEBGL"] = 37442] = "CONTEXT_LOST_WEBGL";
	/** Passed to frontFace to specify the front face of a polygon is drawn in the clockwise direction */
	GLEnum[GLEnum["CW"] = 2304] = "CW";
	/** Passed to frontFace to specify the front face of a polygon is drawn in the counter clockwise direction */
	GLEnum[GLEnum["CCW"] = 2305] = "CCW";
	/** There is no preference for this behavior. */
	GLEnum[GLEnum["DONT_CARE"] = 4352] = "DONT_CARE";
	/** The most efficient behavior should be used. */
	GLEnum[GLEnum["FASTEST"] = 4353] = "FASTEST";
	/** The most correct or the highest quality option should be used. */
	GLEnum[GLEnum["NICEST"] = 4354] = "NICEST";
	/** Hint for the quality of filtering when generating mipmap images with WebGLRenderingContext.generateMipmap(). */
	GLEnum[GLEnum["GENERATE_MIPMAP_HINT"] = 33170] = "GENERATE_MIPMAP_HINT";
	GLEnum[GLEnum["BYTE"] = 5120] = "BYTE";
	GLEnum[GLEnum["UNSIGNED_BYTE"] = 5121] = "UNSIGNED_BYTE";
	GLEnum[GLEnum["SHORT"] = 5122] = "SHORT";
	GLEnum[GLEnum["UNSIGNED_SHORT"] = 5123] = "UNSIGNED_SHORT";
	GLEnum[GLEnum["INT"] = 5124] = "INT";
	GLEnum[GLEnum["UNSIGNED_INT"] = 5125] = "UNSIGNED_INT";
	GLEnum[GLEnum["FLOAT"] = 5126] = "FLOAT";
	GLEnum[GLEnum["DOUBLE"] = 5130] = "DOUBLE";
	GLEnum[GLEnum["DEPTH_COMPONENT"] = 6402] = "DEPTH_COMPONENT";
	GLEnum[GLEnum["ALPHA"] = 6406] = "ALPHA";
	GLEnum[GLEnum["RGB"] = 6407] = "RGB";
	GLEnum[GLEnum["RGBA"] = 6408] = "RGBA";
	GLEnum[GLEnum["LUMINANCE"] = 6409] = "LUMINANCE";
	GLEnum[GLEnum["LUMINANCE_ALPHA"] = 6410] = "LUMINANCE_ALPHA";
	GLEnum[GLEnum["UNSIGNED_SHORT_4_4_4_4"] = 32819] = "UNSIGNED_SHORT_4_4_4_4";
	GLEnum[GLEnum["UNSIGNED_SHORT_5_5_5_1"] = 32820] = "UNSIGNED_SHORT_5_5_5_1";
	GLEnum[GLEnum["UNSIGNED_SHORT_5_6_5"] = 33635] = "UNSIGNED_SHORT_5_6_5";
	/** Passed to createShader to define a fragment shader. */
	GLEnum[GLEnum["FRAGMENT_SHADER"] = 35632] = "FRAGMENT_SHADER";
	/** Passed to createShader to define a vertex shader */
	GLEnum[GLEnum["VERTEX_SHADER"] = 35633] = "VERTEX_SHADER";
	/** Passed to getShaderParameter to get the status of the compilation. Returns false if the shader was not compiled. You can then query getShaderInfoLog to find the exact error */
	GLEnum[GLEnum["COMPILE_STATUS"] = 35713] = "COMPILE_STATUS";
	/** Passed to getShaderParameter to determine if a shader was deleted via deleteShader. Returns true if it was, false otherwise. */
	GLEnum[GLEnum["DELETE_STATUS"] = 35712] = "DELETE_STATUS";
	/** Passed to getProgramParameter after calling linkProgram to determine if a program was linked correctly. Returns false if there were errors. Use getProgramInfoLog to find the exact error. */
	GLEnum[GLEnum["LINK_STATUS"] = 35714] = "LINK_STATUS";
	/** Passed to getProgramParameter after calling validateProgram to determine if it is valid. Returns false if errors were found. */
	GLEnum[GLEnum["VALIDATE_STATUS"] = 35715] = "VALIDATE_STATUS";
	/** Passed to getProgramParameter after calling attachShader to determine if the shader was attached correctly. Returns false if errors occurred. */
	GLEnum[GLEnum["ATTACHED_SHADERS"] = 35717] = "ATTACHED_SHADERS";
	/** Passed to getProgramParameter to get the number of attributes active in a program. */
	GLEnum[GLEnum["ACTIVE_ATTRIBUTES"] = 35721] = "ACTIVE_ATTRIBUTES";
	/** Passed to getProgramParameter to get the number of uniforms active in a program. */
	GLEnum[GLEnum["ACTIVE_UNIFORMS"] = 35718] = "ACTIVE_UNIFORMS";
	/** The maximum number of entries possible in the vertex attribute list. */
	GLEnum[GLEnum["MAX_VERTEX_ATTRIBS"] = 34921] = "MAX_VERTEX_ATTRIBS";
	GLEnum[GLEnum["MAX_VERTEX_UNIFORM_VECTORS"] = 36347] = "MAX_VERTEX_UNIFORM_VECTORS";
	GLEnum[GLEnum["MAX_VARYING_VECTORS"] = 36348] = "MAX_VARYING_VECTORS";
	GLEnum[GLEnum["MAX_COMBINED_TEXTURE_IMAGE_UNITS"] = 35661] = "MAX_COMBINED_TEXTURE_IMAGE_UNITS";
	GLEnum[GLEnum["MAX_VERTEX_TEXTURE_IMAGE_UNITS"] = 35660] = "MAX_VERTEX_TEXTURE_IMAGE_UNITS";
	/** Implementation dependent number of maximum texture units. At least 8. */
	GLEnum[GLEnum["MAX_TEXTURE_IMAGE_UNITS"] = 34930] = "MAX_TEXTURE_IMAGE_UNITS";
	GLEnum[GLEnum["MAX_FRAGMENT_UNIFORM_VECTORS"] = 36349] = "MAX_FRAGMENT_UNIFORM_VECTORS";
	GLEnum[GLEnum["SHADER_TYPE"] = 35663] = "SHADER_TYPE";
	GLEnum[GLEnum["SHADING_LANGUAGE_VERSION"] = 35724] = "SHADING_LANGUAGE_VERSION";
	GLEnum[GLEnum["CURRENT_PROGRAM"] = 35725] = "CURRENT_PROGRAM";
	/** Passed to depthFunction or stencilFunction to specify depth or stencil tests will never pass, i.e., nothing will be drawn. */
	GLEnum[GLEnum["NEVER"] = 512] = "NEVER";
	/** Passed to depthFunction or stencilFunction to specify depth or stencil tests will pass if the new depth value is less than the stored value. */
	GLEnum[GLEnum["LESS"] = 513] = "LESS";
	/** Passed to depthFunction or stencilFunction to specify depth or stencil tests will pass if the new depth value is equals to the stored value. */
	GLEnum[GLEnum["EQUAL"] = 514] = "EQUAL";
	/** Passed to depthFunction or stencilFunction to specify depth or stencil tests will pass if the new depth value is less than or equal to the stored value. */
	GLEnum[GLEnum["LEQUAL"] = 515] = "LEQUAL";
	/** Passed to depthFunction or stencilFunction to specify depth or stencil tests will pass if the new depth value is greater than the stored value. */
	GLEnum[GLEnum["GREATER"] = 516] = "GREATER";
	/** Passed to depthFunction or stencilFunction to specify depth or stencil tests will pass if the new depth value is not equal to the stored value. */
	GLEnum[GLEnum["NOTEQUAL"] = 517] = "NOTEQUAL";
	/** Passed to depthFunction or stencilFunction to specify depth or stencil tests will pass if the new depth value is greater than or equal to the stored value. */
	GLEnum[GLEnum["GEQUAL"] = 518] = "GEQUAL";
	/** Passed to depthFunction or stencilFunction to specify depth or stencil tests will always pass, i.e., pixels will be drawn in the order they are drawn. */
	GLEnum[GLEnum["ALWAYS"] = 519] = "ALWAYS";
	GLEnum[GLEnum["KEEP"] = 7680] = "KEEP";
	GLEnum[GLEnum["REPLACE"] = 7681] = "REPLACE";
	GLEnum[GLEnum["INCR"] = 7682] = "INCR";
	GLEnum[GLEnum["DECR"] = 7683] = "DECR";
	GLEnum[GLEnum["INVERT"] = 5386] = "INVERT";
	GLEnum[GLEnum["INCR_WRAP"] = 34055] = "INCR_WRAP";
	GLEnum[GLEnum["DECR_WRAP"] = 34056] = "DECR_WRAP";
	GLEnum[GLEnum["NEAREST"] = 9728] = "NEAREST";
	GLEnum[GLEnum["LINEAR"] = 9729] = "LINEAR";
	GLEnum[GLEnum["NEAREST_MIPMAP_NEAREST"] = 9984] = "NEAREST_MIPMAP_NEAREST";
	GLEnum[GLEnum["LINEAR_MIPMAP_NEAREST"] = 9985] = "LINEAR_MIPMAP_NEAREST";
	GLEnum[GLEnum["NEAREST_MIPMAP_LINEAR"] = 9986] = "NEAREST_MIPMAP_LINEAR";
	GLEnum[GLEnum["LINEAR_MIPMAP_LINEAR"] = 9987] = "LINEAR_MIPMAP_LINEAR";
	/** The texture magnification function is used when the pixel being textured maps to an area less than or equal to one texture element. It sets the texture magnification function to either GL_NEAREST or GL_LINEAR (see below). GL_NEAREST is generally faster than GL_LINEAR, but it can produce textured images with sharper edges because the transition between texture elements is not as smooth. Default: GL_LINEAR.  */
	GLEnum[GLEnum["TEXTURE_MAG_FILTER"] = 10240] = "TEXTURE_MAG_FILTER";
	/** The texture minifying function is used whenever the pixel being textured maps to an area greater than one texture element. There are six defined minifying functions. Two of them use the nearest one or nearest four texture elements to compute the texture value. The other four use mipmaps. Default: GL_NEAREST_MIPMAP_LINEAR */
	GLEnum[GLEnum["TEXTURE_MIN_FILTER"] = 10241] = "TEXTURE_MIN_FILTER";
	/** Sets the wrap parameter for texture coordinate  to either GL_CLAMP_TO_EDGE, GL_MIRRORED_REPEAT, or GL_REPEAT. G */
	GLEnum[GLEnum["TEXTURE_WRAP_S"] = 10242] = "TEXTURE_WRAP_S";
	/** Sets the wrap parameter for texture coordinate  to either GL_CLAMP_TO_EDGE, GL_MIRRORED_REPEAT, or GL_REPEAT. G */
	GLEnum[GLEnum["TEXTURE_WRAP_T"] = 10243] = "TEXTURE_WRAP_T";
	GLEnum[GLEnum["TEXTURE_2D"] = 3553] = "TEXTURE_2D";
	GLEnum[GLEnum["TEXTURE"] = 5890] = "TEXTURE";
	GLEnum[GLEnum["TEXTURE_CUBE_MAP"] = 34067] = "TEXTURE_CUBE_MAP";
	GLEnum[GLEnum["TEXTURE_BINDING_CUBE_MAP"] = 34068] = "TEXTURE_BINDING_CUBE_MAP";
	GLEnum[GLEnum["TEXTURE_CUBE_MAP_POSITIVE_X"] = 34069] = "TEXTURE_CUBE_MAP_POSITIVE_X";
	GLEnum[GLEnum["TEXTURE_CUBE_MAP_NEGATIVE_X"] = 34070] = "TEXTURE_CUBE_MAP_NEGATIVE_X";
	GLEnum[GLEnum["TEXTURE_CUBE_MAP_POSITIVE_Y"] = 34071] = "TEXTURE_CUBE_MAP_POSITIVE_Y";
	GLEnum[GLEnum["TEXTURE_CUBE_MAP_NEGATIVE_Y"] = 34072] = "TEXTURE_CUBE_MAP_NEGATIVE_Y";
	GLEnum[GLEnum["TEXTURE_CUBE_MAP_POSITIVE_Z"] = 34073] = "TEXTURE_CUBE_MAP_POSITIVE_Z";
	GLEnum[GLEnum["TEXTURE_CUBE_MAP_NEGATIVE_Z"] = 34074] = "TEXTURE_CUBE_MAP_NEGATIVE_Z";
	GLEnum[GLEnum["MAX_CUBE_MAP_TEXTURE_SIZE"] = 34076] = "MAX_CUBE_MAP_TEXTURE_SIZE";
	GLEnum[GLEnum["TEXTURE0"] = 33984] = "TEXTURE0";
	GLEnum[GLEnum["ACTIVE_TEXTURE"] = 34016] = "ACTIVE_TEXTURE";
	GLEnum[GLEnum["REPEAT"] = 10497] = "REPEAT";
	GLEnum[GLEnum["CLAMP_TO_EDGE"] = 33071] = "CLAMP_TO_EDGE";
	GLEnum[GLEnum["MIRRORED_REPEAT"] = 33648] = "MIRRORED_REPEAT";
	GLEnum[GLEnum["TEXTURE_WIDTH"] = 4096] = "TEXTURE_WIDTH";
	GLEnum[GLEnum["TEXTURE_HEIGHT"] = 4097] = "TEXTURE_HEIGHT";
	GLEnum[GLEnum["FLOAT_VEC2"] = 35664] = "FLOAT_VEC2";
	GLEnum[GLEnum["FLOAT_VEC3"] = 35665] = "FLOAT_VEC3";
	GLEnum[GLEnum["FLOAT_VEC4"] = 35666] = "FLOAT_VEC4";
	GLEnum[GLEnum["INT_VEC2"] = 35667] = "INT_VEC2";
	GLEnum[GLEnum["INT_VEC3"] = 35668] = "INT_VEC3";
	GLEnum[GLEnum["INT_VEC4"] = 35669] = "INT_VEC4";
	GLEnum[GLEnum["BOOL"] = 35670] = "BOOL";
	GLEnum[GLEnum["BOOL_VEC2"] = 35671] = "BOOL_VEC2";
	GLEnum[GLEnum["BOOL_VEC3"] = 35672] = "BOOL_VEC3";
	GLEnum[GLEnum["BOOL_VEC4"] = 35673] = "BOOL_VEC4";
	GLEnum[GLEnum["FLOAT_MAT2"] = 35674] = "FLOAT_MAT2";
	GLEnum[GLEnum["FLOAT_MAT3"] = 35675] = "FLOAT_MAT3";
	GLEnum[GLEnum["FLOAT_MAT4"] = 35676] = "FLOAT_MAT4";
	GLEnum[GLEnum["SAMPLER_2D"] = 35678] = "SAMPLER_2D";
	GLEnum[GLEnum["SAMPLER_CUBE"] = 35680] = "SAMPLER_CUBE";
	GLEnum[GLEnum["LOW_FLOAT"] = 36336] = "LOW_FLOAT";
	GLEnum[GLEnum["MEDIUM_FLOAT"] = 36337] = "MEDIUM_FLOAT";
	GLEnum[GLEnum["HIGH_FLOAT"] = 36338] = "HIGH_FLOAT";
	GLEnum[GLEnum["LOW_INT"] = 36339] = "LOW_INT";
	GLEnum[GLEnum["MEDIUM_INT"] = 36340] = "MEDIUM_INT";
	GLEnum[GLEnum["HIGH_INT"] = 36341] = "HIGH_INT";
	GLEnum[GLEnum["FRAMEBUFFER"] = 36160] = "FRAMEBUFFER";
	GLEnum[GLEnum["RENDERBUFFER"] = 36161] = "RENDERBUFFER";
	GLEnum[GLEnum["RGBA4"] = 32854] = "RGBA4";
	GLEnum[GLEnum["RGB5_A1"] = 32855] = "RGB5_A1";
	GLEnum[GLEnum["RGB565"] = 36194] = "RGB565";
	GLEnum[GLEnum["DEPTH_COMPONENT16"] = 33189] = "DEPTH_COMPONENT16";
	GLEnum[GLEnum["STENCIL_INDEX"] = 6401] = "STENCIL_INDEX";
	GLEnum[GLEnum["STENCIL_INDEX8"] = 36168] = "STENCIL_INDEX8";
	GLEnum[GLEnum["DEPTH_STENCIL"] = 34041] = "DEPTH_STENCIL";
	GLEnum[GLEnum["RENDERBUFFER_WIDTH"] = 36162] = "RENDERBUFFER_WIDTH";
	GLEnum[GLEnum["RENDERBUFFER_HEIGHT"] = 36163] = "RENDERBUFFER_HEIGHT";
	GLEnum[GLEnum["RENDERBUFFER_INTERNAL_FORMAT"] = 36164] = "RENDERBUFFER_INTERNAL_FORMAT";
	GLEnum[GLEnum["RENDERBUFFER_RED_SIZE"] = 36176] = "RENDERBUFFER_RED_SIZE";
	GLEnum[GLEnum["RENDERBUFFER_GREEN_SIZE"] = 36177] = "RENDERBUFFER_GREEN_SIZE";
	GLEnum[GLEnum["RENDERBUFFER_BLUE_SIZE"] = 36178] = "RENDERBUFFER_BLUE_SIZE";
	GLEnum[GLEnum["RENDERBUFFER_ALPHA_SIZE"] = 36179] = "RENDERBUFFER_ALPHA_SIZE";
	GLEnum[GLEnum["RENDERBUFFER_DEPTH_SIZE"] = 36180] = "RENDERBUFFER_DEPTH_SIZE";
	GLEnum[GLEnum["RENDERBUFFER_STENCIL_SIZE"] = 36181] = "RENDERBUFFER_STENCIL_SIZE";
	GLEnum[GLEnum["FRAMEBUFFER_ATTACHMENT_OBJECT_TYPE"] = 36048] = "FRAMEBUFFER_ATTACHMENT_OBJECT_TYPE";
	GLEnum[GLEnum["FRAMEBUFFER_ATTACHMENT_OBJECT_NAME"] = 36049] = "FRAMEBUFFER_ATTACHMENT_OBJECT_NAME";
	GLEnum[GLEnum["FRAMEBUFFER_ATTACHMENT_TEXTURE_LEVEL"] = 36050] = "FRAMEBUFFER_ATTACHMENT_TEXTURE_LEVEL";
	GLEnum[GLEnum["FRAMEBUFFER_ATTACHMENT_TEXTURE_CUBE_MAP_FACE"] = 36051] = "FRAMEBUFFER_ATTACHMENT_TEXTURE_CUBE_MAP_FACE";
	GLEnum[GLEnum["COLOR_ATTACHMENT0"] = 36064] = "COLOR_ATTACHMENT0";
	GLEnum[GLEnum["DEPTH_ATTACHMENT"] = 36096] = "DEPTH_ATTACHMENT";
	GLEnum[GLEnum["STENCIL_ATTACHMENT"] = 36128] = "STENCIL_ATTACHMENT";
	GLEnum[GLEnum["DEPTH_STENCIL_ATTACHMENT"] = 33306] = "DEPTH_STENCIL_ATTACHMENT";
	GLEnum[GLEnum["NONE"] = 0] = "NONE";
	GLEnum[GLEnum["FRAMEBUFFER_COMPLETE"] = 36053] = "FRAMEBUFFER_COMPLETE";
	GLEnum[GLEnum["FRAMEBUFFER_INCOMPLETE_ATTACHMENT"] = 36054] = "FRAMEBUFFER_INCOMPLETE_ATTACHMENT";
	GLEnum[GLEnum["FRAMEBUFFER_INCOMPLETE_MISSING_ATTACHMENT"] = 36055] = "FRAMEBUFFER_INCOMPLETE_MISSING_ATTACHMENT";
	GLEnum[GLEnum["FRAMEBUFFER_INCOMPLETE_DIMENSIONS"] = 36057] = "FRAMEBUFFER_INCOMPLETE_DIMENSIONS";
	GLEnum[GLEnum["FRAMEBUFFER_UNSUPPORTED"] = 36061] = "FRAMEBUFFER_UNSUPPORTED";
	GLEnum[GLEnum["FRAMEBUFFER_BINDING"] = 36006] = "FRAMEBUFFER_BINDING";
	GLEnum[GLEnum["RENDERBUFFER_BINDING"] = 36007] = "RENDERBUFFER_BINDING";
	GLEnum[GLEnum["READ_FRAMEBUFFER"] = 36008] = "READ_FRAMEBUFFER";
	GLEnum[GLEnum["DRAW_FRAMEBUFFER"] = 36009] = "DRAW_FRAMEBUFFER";
	GLEnum[GLEnum["MAX_RENDERBUFFER_SIZE"] = 34024] = "MAX_RENDERBUFFER_SIZE";
	GLEnum[GLEnum["INVALID_FRAMEBUFFER_OPERATION"] = 1286] = "INVALID_FRAMEBUFFER_OPERATION";
	GLEnum[GLEnum["UNPACK_FLIP_Y_WEBGL"] = 37440] = "UNPACK_FLIP_Y_WEBGL";
	GLEnum[GLEnum["UNPACK_PREMULTIPLY_ALPHA_WEBGL"] = 37441] = "UNPACK_PREMULTIPLY_ALPHA_WEBGL";
	GLEnum[GLEnum["UNPACK_COLORSPACE_CONVERSION_WEBGL"] = 37443] = "UNPACK_COLORSPACE_CONVERSION_WEBGL";
	GLEnum[GLEnum["READ_BUFFER"] = 3074] = "READ_BUFFER";
	GLEnum[GLEnum["UNPACK_ROW_LENGTH"] = 3314] = "UNPACK_ROW_LENGTH";
	GLEnum[GLEnum["UNPACK_SKIP_ROWS"] = 3315] = "UNPACK_SKIP_ROWS";
	GLEnum[GLEnum["UNPACK_SKIP_PIXELS"] = 3316] = "UNPACK_SKIP_PIXELS";
	GLEnum[GLEnum["PACK_ROW_LENGTH"] = 3330] = "PACK_ROW_LENGTH";
	GLEnum[GLEnum["PACK_SKIP_ROWS"] = 3331] = "PACK_SKIP_ROWS";
	GLEnum[GLEnum["PACK_SKIP_PIXELS"] = 3332] = "PACK_SKIP_PIXELS";
	GLEnum[GLEnum["TEXTURE_BINDING_3D"] = 32874] = "TEXTURE_BINDING_3D";
	GLEnum[GLEnum["UNPACK_SKIP_IMAGES"] = 32877] = "UNPACK_SKIP_IMAGES";
	GLEnum[GLEnum["UNPACK_IMAGE_HEIGHT"] = 32878] = "UNPACK_IMAGE_HEIGHT";
	GLEnum[GLEnum["MAX_3D_TEXTURE_SIZE"] = 32883] = "MAX_3D_TEXTURE_SIZE";
	GLEnum[GLEnum["MAX_ELEMENTS_VERTICES"] = 33e3] = "MAX_ELEMENTS_VERTICES";
	GLEnum[GLEnum["MAX_ELEMENTS_INDICES"] = 33001] = "MAX_ELEMENTS_INDICES";
	GLEnum[GLEnum["MAX_TEXTURE_LOD_BIAS"] = 34045] = "MAX_TEXTURE_LOD_BIAS";
	GLEnum[GLEnum["MAX_FRAGMENT_UNIFORM_COMPONENTS"] = 35657] = "MAX_FRAGMENT_UNIFORM_COMPONENTS";
	GLEnum[GLEnum["MAX_VERTEX_UNIFORM_COMPONENTS"] = 35658] = "MAX_VERTEX_UNIFORM_COMPONENTS";
	GLEnum[GLEnum["MAX_ARRAY_TEXTURE_LAYERS"] = 35071] = "MAX_ARRAY_TEXTURE_LAYERS";
	GLEnum[GLEnum["MIN_PROGRAM_TEXEL_OFFSET"] = 35076] = "MIN_PROGRAM_TEXEL_OFFSET";
	GLEnum[GLEnum["MAX_PROGRAM_TEXEL_OFFSET"] = 35077] = "MAX_PROGRAM_TEXEL_OFFSET";
	GLEnum[GLEnum["MAX_VARYING_COMPONENTS"] = 35659] = "MAX_VARYING_COMPONENTS";
	GLEnum[GLEnum["FRAGMENT_SHADER_DERIVATIVE_HINT"] = 35723] = "FRAGMENT_SHADER_DERIVATIVE_HINT";
	GLEnum[GLEnum["RASTERIZER_DISCARD"] = 35977] = "RASTERIZER_DISCARD";
	GLEnum[GLEnum["VERTEX_ARRAY_BINDING"] = 34229] = "VERTEX_ARRAY_BINDING";
	GLEnum[GLEnum["MAX_VERTEX_OUTPUT_COMPONENTS"] = 37154] = "MAX_VERTEX_OUTPUT_COMPONENTS";
	GLEnum[GLEnum["MAX_FRAGMENT_INPUT_COMPONENTS"] = 37157] = "MAX_FRAGMENT_INPUT_COMPONENTS";
	GLEnum[GLEnum["MAX_SERVER_WAIT_TIMEOUT"] = 37137] = "MAX_SERVER_WAIT_TIMEOUT";
	GLEnum[GLEnum["MAX_ELEMENT_INDEX"] = 36203] = "MAX_ELEMENT_INDEX";
	GLEnum[GLEnum["RED"] = 6403] = "RED";
	GLEnum[GLEnum["RGB8"] = 32849] = "RGB8";
	GLEnum[GLEnum["RGBA8"] = 32856] = "RGBA8";
	GLEnum[GLEnum["RGB10_A2"] = 32857] = "RGB10_A2";
	GLEnum[GLEnum["TEXTURE_3D"] = 32879] = "TEXTURE_3D";
	/** Sets the wrap parameter for texture coordinate  to either GL_CLAMP_TO_EDGE, GL_MIRRORED_REPEAT, or GL_REPEAT. G */
	GLEnum[GLEnum["TEXTURE_WRAP_R"] = 32882] = "TEXTURE_WRAP_R";
	GLEnum[GLEnum["TEXTURE_MIN_LOD"] = 33082] = "TEXTURE_MIN_LOD";
	GLEnum[GLEnum["TEXTURE_MAX_LOD"] = 33083] = "TEXTURE_MAX_LOD";
	GLEnum[GLEnum["TEXTURE_BASE_LEVEL"] = 33084] = "TEXTURE_BASE_LEVEL";
	GLEnum[GLEnum["TEXTURE_MAX_LEVEL"] = 33085] = "TEXTURE_MAX_LEVEL";
	GLEnum[GLEnum["TEXTURE_COMPARE_MODE"] = 34892] = "TEXTURE_COMPARE_MODE";
	GLEnum[GLEnum["TEXTURE_COMPARE_FUNC"] = 34893] = "TEXTURE_COMPARE_FUNC";
	GLEnum[GLEnum["SRGB"] = 35904] = "SRGB";
	GLEnum[GLEnum["SRGB8"] = 35905] = "SRGB8";
	GLEnum[GLEnum["SRGB8_ALPHA8"] = 35907] = "SRGB8_ALPHA8";
	GLEnum[GLEnum["COMPARE_REF_TO_TEXTURE"] = 34894] = "COMPARE_REF_TO_TEXTURE";
	GLEnum[GLEnum["RGBA32F"] = 34836] = "RGBA32F";
	GLEnum[GLEnum["RGB32F"] = 34837] = "RGB32F";
	GLEnum[GLEnum["RGBA16F"] = 34842] = "RGBA16F";
	GLEnum[GLEnum["RGB16F"] = 34843] = "RGB16F";
	GLEnum[GLEnum["TEXTURE_2D_ARRAY"] = 35866] = "TEXTURE_2D_ARRAY";
	GLEnum[GLEnum["TEXTURE_BINDING_2D_ARRAY"] = 35869] = "TEXTURE_BINDING_2D_ARRAY";
	GLEnum[GLEnum["R11F_G11F_B10F"] = 35898] = "R11F_G11F_B10F";
	GLEnum[GLEnum["RGB9_E5"] = 35901] = "RGB9_E5";
	GLEnum[GLEnum["RGBA32UI"] = 36208] = "RGBA32UI";
	GLEnum[GLEnum["RGB32UI"] = 36209] = "RGB32UI";
	GLEnum[GLEnum["RGBA16UI"] = 36214] = "RGBA16UI";
	GLEnum[GLEnum["RGB16UI"] = 36215] = "RGB16UI";
	GLEnum[GLEnum["RGBA8UI"] = 36220] = "RGBA8UI";
	GLEnum[GLEnum["RGB8UI"] = 36221] = "RGB8UI";
	GLEnum[GLEnum["RGBA32I"] = 36226] = "RGBA32I";
	GLEnum[GLEnum["RGB32I"] = 36227] = "RGB32I";
	GLEnum[GLEnum["RGBA16I"] = 36232] = "RGBA16I";
	GLEnum[GLEnum["RGB16I"] = 36233] = "RGB16I";
	GLEnum[GLEnum["RGBA8I"] = 36238] = "RGBA8I";
	GLEnum[GLEnum["RGB8I"] = 36239] = "RGB8I";
	GLEnum[GLEnum["RED_INTEGER"] = 36244] = "RED_INTEGER";
	GLEnum[GLEnum["RGB_INTEGER"] = 36248] = "RGB_INTEGER";
	GLEnum[GLEnum["RGBA_INTEGER"] = 36249] = "RGBA_INTEGER";
	GLEnum[GLEnum["R8"] = 33321] = "R8";
	GLEnum[GLEnum["RG8"] = 33323] = "RG8";
	GLEnum[GLEnum["R16F"] = 33325] = "R16F";
	GLEnum[GLEnum["R32F"] = 33326] = "R32F";
	GLEnum[GLEnum["RG16F"] = 33327] = "RG16F";
	GLEnum[GLEnum["RG32F"] = 33328] = "RG32F";
	GLEnum[GLEnum["R8I"] = 33329] = "R8I";
	GLEnum[GLEnum["R8UI"] = 33330] = "R8UI";
	GLEnum[GLEnum["R16I"] = 33331] = "R16I";
	GLEnum[GLEnum["R16UI"] = 33332] = "R16UI";
	GLEnum[GLEnum["R32I"] = 33333] = "R32I";
	GLEnum[GLEnum["R32UI"] = 33334] = "R32UI";
	GLEnum[GLEnum["RG8I"] = 33335] = "RG8I";
	GLEnum[GLEnum["RG8UI"] = 33336] = "RG8UI";
	GLEnum[GLEnum["RG16I"] = 33337] = "RG16I";
	GLEnum[GLEnum["RG16UI"] = 33338] = "RG16UI";
	GLEnum[GLEnum["RG32I"] = 33339] = "RG32I";
	GLEnum[GLEnum["RG32UI"] = 33340] = "RG32UI";
	GLEnum[GLEnum["R8_SNORM"] = 36756] = "R8_SNORM";
	GLEnum[GLEnum["RG8_SNORM"] = 36757] = "RG8_SNORM";
	GLEnum[GLEnum["RGB8_SNORM"] = 36758] = "RGB8_SNORM";
	GLEnum[GLEnum["RGBA8_SNORM"] = 36759] = "RGBA8_SNORM";
	GLEnum[GLEnum["RGB10_A2UI"] = 36975] = "RGB10_A2UI";
	GLEnum[GLEnum["TEXTURE_IMMUTABLE_FORMAT"] = 37167] = "TEXTURE_IMMUTABLE_FORMAT";
	GLEnum[GLEnum["TEXTURE_IMMUTABLE_LEVELS"] = 33503] = "TEXTURE_IMMUTABLE_LEVELS";
	GLEnum[GLEnum["UNSIGNED_INT_2_10_10_10_REV"] = 33640] = "UNSIGNED_INT_2_10_10_10_REV";
	GLEnum[GLEnum["UNSIGNED_INT_10F_11F_11F_REV"] = 35899] = "UNSIGNED_INT_10F_11F_11F_REV";
	GLEnum[GLEnum["UNSIGNED_INT_5_9_9_9_REV"] = 35902] = "UNSIGNED_INT_5_9_9_9_REV";
	GLEnum[GLEnum["FLOAT_32_UNSIGNED_INT_24_8_REV"] = 36269] = "FLOAT_32_UNSIGNED_INT_24_8_REV";
	GLEnum[GLEnum["UNSIGNED_INT_24_8"] = 34042] = "UNSIGNED_INT_24_8";
	GLEnum[GLEnum["HALF_FLOAT"] = 5131] = "HALF_FLOAT";
	GLEnum[GLEnum["RG"] = 33319] = "RG";
	GLEnum[GLEnum["RG_INTEGER"] = 33320] = "RG_INTEGER";
	GLEnum[GLEnum["INT_2_10_10_10_REV"] = 36255] = "INT_2_10_10_10_REV";
	GLEnum[GLEnum["CURRENT_QUERY"] = 34917] = "CURRENT_QUERY";
	/** Returns a GLuint containing the query result. */
	GLEnum[GLEnum["QUERY_RESULT"] = 34918] = "QUERY_RESULT";
	/** Whether query result is available. */
	GLEnum[GLEnum["QUERY_RESULT_AVAILABLE"] = 34919] = "QUERY_RESULT_AVAILABLE";
	/** Occlusion query (if drawing passed depth test)  */
	GLEnum[GLEnum["ANY_SAMPLES_PASSED"] = 35887] = "ANY_SAMPLES_PASSED";
	/** Occlusion query less accurate/faster version */
	GLEnum[GLEnum["ANY_SAMPLES_PASSED_CONSERVATIVE"] = 36202] = "ANY_SAMPLES_PASSED_CONSERVATIVE";
	GLEnum[GLEnum["MAX_DRAW_BUFFERS"] = 34852] = "MAX_DRAW_BUFFERS";
	GLEnum[GLEnum["DRAW_BUFFER0"] = 34853] = "DRAW_BUFFER0";
	GLEnum[GLEnum["DRAW_BUFFER1"] = 34854] = "DRAW_BUFFER1";
	GLEnum[GLEnum["DRAW_BUFFER2"] = 34855] = "DRAW_BUFFER2";
	GLEnum[GLEnum["DRAW_BUFFER3"] = 34856] = "DRAW_BUFFER3";
	GLEnum[GLEnum["DRAW_BUFFER4"] = 34857] = "DRAW_BUFFER4";
	GLEnum[GLEnum["DRAW_BUFFER5"] = 34858] = "DRAW_BUFFER5";
	GLEnum[GLEnum["DRAW_BUFFER6"] = 34859] = "DRAW_BUFFER6";
	GLEnum[GLEnum["DRAW_BUFFER7"] = 34860] = "DRAW_BUFFER7";
	GLEnum[GLEnum["DRAW_BUFFER8"] = 34861] = "DRAW_BUFFER8";
	GLEnum[GLEnum["DRAW_BUFFER9"] = 34862] = "DRAW_BUFFER9";
	GLEnum[GLEnum["DRAW_BUFFER10"] = 34863] = "DRAW_BUFFER10";
	GLEnum[GLEnum["DRAW_BUFFER11"] = 34864] = "DRAW_BUFFER11";
	GLEnum[GLEnum["DRAW_BUFFER12"] = 34865] = "DRAW_BUFFER12";
	GLEnum[GLEnum["DRAW_BUFFER13"] = 34866] = "DRAW_BUFFER13";
	GLEnum[GLEnum["DRAW_BUFFER14"] = 34867] = "DRAW_BUFFER14";
	GLEnum[GLEnum["DRAW_BUFFER15"] = 34868] = "DRAW_BUFFER15";
	GLEnum[GLEnum["MAX_COLOR_ATTACHMENTS"] = 36063] = "MAX_COLOR_ATTACHMENTS";
	GLEnum[GLEnum["COLOR_ATTACHMENT1"] = 36065] = "COLOR_ATTACHMENT1";
	GLEnum[GLEnum["COLOR_ATTACHMENT2"] = 36066] = "COLOR_ATTACHMENT2";
	GLEnum[GLEnum["COLOR_ATTACHMENT3"] = 36067] = "COLOR_ATTACHMENT3";
	GLEnum[GLEnum["COLOR_ATTACHMENT4"] = 36068] = "COLOR_ATTACHMENT4";
	GLEnum[GLEnum["COLOR_ATTACHMENT5"] = 36069] = "COLOR_ATTACHMENT5";
	GLEnum[GLEnum["COLOR_ATTACHMENT6"] = 36070] = "COLOR_ATTACHMENT6";
	GLEnum[GLEnum["COLOR_ATTACHMENT7"] = 36071] = "COLOR_ATTACHMENT7";
	GLEnum[GLEnum["COLOR_ATTACHMENT8"] = 36072] = "COLOR_ATTACHMENT8";
	GLEnum[GLEnum["COLOR_ATTACHMENT9"] = 36073] = "COLOR_ATTACHMENT9";
	GLEnum[GLEnum["COLOR_ATTACHMENT10"] = 36074] = "COLOR_ATTACHMENT10";
	GLEnum[GLEnum["COLOR_ATTACHMENT11"] = 36075] = "COLOR_ATTACHMENT11";
	GLEnum[GLEnum["COLOR_ATTACHMENT12"] = 36076] = "COLOR_ATTACHMENT12";
	GLEnum[GLEnum["COLOR_ATTACHMENT13"] = 36077] = "COLOR_ATTACHMENT13";
	GLEnum[GLEnum["COLOR_ATTACHMENT14"] = 36078] = "COLOR_ATTACHMENT14";
	GLEnum[GLEnum["COLOR_ATTACHMENT15"] = 36079] = "COLOR_ATTACHMENT15";
	GLEnum[GLEnum["SAMPLER_3D"] = 35679] = "SAMPLER_3D";
	GLEnum[GLEnum["SAMPLER_2D_SHADOW"] = 35682] = "SAMPLER_2D_SHADOW";
	GLEnum[GLEnum["SAMPLER_2D_ARRAY"] = 36289] = "SAMPLER_2D_ARRAY";
	GLEnum[GLEnum["SAMPLER_2D_ARRAY_SHADOW"] = 36292] = "SAMPLER_2D_ARRAY_SHADOW";
	GLEnum[GLEnum["SAMPLER_CUBE_SHADOW"] = 36293] = "SAMPLER_CUBE_SHADOW";
	GLEnum[GLEnum["INT_SAMPLER_2D"] = 36298] = "INT_SAMPLER_2D";
	GLEnum[GLEnum["INT_SAMPLER_3D"] = 36299] = "INT_SAMPLER_3D";
	GLEnum[GLEnum["INT_SAMPLER_CUBE"] = 36300] = "INT_SAMPLER_CUBE";
	GLEnum[GLEnum["INT_SAMPLER_2D_ARRAY"] = 36303] = "INT_SAMPLER_2D_ARRAY";
	GLEnum[GLEnum["UNSIGNED_INT_SAMPLER_2D"] = 36306] = "UNSIGNED_INT_SAMPLER_2D";
	GLEnum[GLEnum["UNSIGNED_INT_SAMPLER_3D"] = 36307] = "UNSIGNED_INT_SAMPLER_3D";
	GLEnum[GLEnum["UNSIGNED_INT_SAMPLER_CUBE"] = 36308] = "UNSIGNED_INT_SAMPLER_CUBE";
	GLEnum[GLEnum["UNSIGNED_INT_SAMPLER_2D_ARRAY"] = 36311] = "UNSIGNED_INT_SAMPLER_2D_ARRAY";
	GLEnum[GLEnum["MAX_SAMPLES"] = 36183] = "MAX_SAMPLES";
	GLEnum[GLEnum["SAMPLER_BINDING"] = 35097] = "SAMPLER_BINDING";
	GLEnum[GLEnum["PIXEL_PACK_BUFFER"] = 35051] = "PIXEL_PACK_BUFFER";
	GLEnum[GLEnum["PIXEL_UNPACK_BUFFER"] = 35052] = "PIXEL_UNPACK_BUFFER";
	GLEnum[GLEnum["PIXEL_PACK_BUFFER_BINDING"] = 35053] = "PIXEL_PACK_BUFFER_BINDING";
	GLEnum[GLEnum["PIXEL_UNPACK_BUFFER_BINDING"] = 35055] = "PIXEL_UNPACK_BUFFER_BINDING";
	GLEnum[GLEnum["COPY_READ_BUFFER"] = 36662] = "COPY_READ_BUFFER";
	GLEnum[GLEnum["COPY_WRITE_BUFFER"] = 36663] = "COPY_WRITE_BUFFER";
	GLEnum[GLEnum["COPY_READ_BUFFER_BINDING"] = 36662] = "COPY_READ_BUFFER_BINDING";
	GLEnum[GLEnum["COPY_WRITE_BUFFER_BINDING"] = 36663] = "COPY_WRITE_BUFFER_BINDING";
	GLEnum[GLEnum["FLOAT_MAT2x3"] = 35685] = "FLOAT_MAT2x3";
	GLEnum[GLEnum["FLOAT_MAT2x4"] = 35686] = "FLOAT_MAT2x4";
	GLEnum[GLEnum["FLOAT_MAT3x2"] = 35687] = "FLOAT_MAT3x2";
	GLEnum[GLEnum["FLOAT_MAT3x4"] = 35688] = "FLOAT_MAT3x4";
	GLEnum[GLEnum["FLOAT_MAT4x2"] = 35689] = "FLOAT_MAT4x2";
	GLEnum[GLEnum["FLOAT_MAT4x3"] = 35690] = "FLOAT_MAT4x3";
	GLEnum[GLEnum["UNSIGNED_INT_VEC2"] = 36294] = "UNSIGNED_INT_VEC2";
	GLEnum[GLEnum["UNSIGNED_INT_VEC3"] = 36295] = "UNSIGNED_INT_VEC3";
	GLEnum[GLEnum["UNSIGNED_INT_VEC4"] = 36296] = "UNSIGNED_INT_VEC4";
	GLEnum[GLEnum["UNSIGNED_NORMALIZED"] = 35863] = "UNSIGNED_NORMALIZED";
	GLEnum[GLEnum["SIGNED_NORMALIZED"] = 36764] = "SIGNED_NORMALIZED";
	GLEnum[GLEnum["VERTEX_ATTRIB_ARRAY_INTEGER"] = 35069] = "VERTEX_ATTRIB_ARRAY_INTEGER";
	GLEnum[GLEnum["VERTEX_ATTRIB_ARRAY_DIVISOR"] = 35070] = "VERTEX_ATTRIB_ARRAY_DIVISOR";
	GLEnum[GLEnum["TRANSFORM_FEEDBACK_BUFFER_MODE"] = 35967] = "TRANSFORM_FEEDBACK_BUFFER_MODE";
	GLEnum[GLEnum["MAX_TRANSFORM_FEEDBACK_SEPARATE_COMPONENTS"] = 35968] = "MAX_TRANSFORM_FEEDBACK_SEPARATE_COMPONENTS";
	GLEnum[GLEnum["TRANSFORM_FEEDBACK_VARYINGS"] = 35971] = "TRANSFORM_FEEDBACK_VARYINGS";
	GLEnum[GLEnum["TRANSFORM_FEEDBACK_BUFFER_START"] = 35972] = "TRANSFORM_FEEDBACK_BUFFER_START";
	GLEnum[GLEnum["TRANSFORM_FEEDBACK_BUFFER_SIZE"] = 35973] = "TRANSFORM_FEEDBACK_BUFFER_SIZE";
	GLEnum[GLEnum["TRANSFORM_FEEDBACK_PRIMITIVES_WRITTEN"] = 35976] = "TRANSFORM_FEEDBACK_PRIMITIVES_WRITTEN";
	GLEnum[GLEnum["MAX_TRANSFORM_FEEDBACK_INTERLEAVED_COMPONENTS"] = 35978] = "MAX_TRANSFORM_FEEDBACK_INTERLEAVED_COMPONENTS";
	GLEnum[GLEnum["MAX_TRANSFORM_FEEDBACK_SEPARATE_ATTRIBS"] = 35979] = "MAX_TRANSFORM_FEEDBACK_SEPARATE_ATTRIBS";
	GLEnum[GLEnum["INTERLEAVED_ATTRIBS"] = 35980] = "INTERLEAVED_ATTRIBS";
	GLEnum[GLEnum["SEPARATE_ATTRIBS"] = 35981] = "SEPARATE_ATTRIBS";
	GLEnum[GLEnum["TRANSFORM_FEEDBACK_BUFFER"] = 35982] = "TRANSFORM_FEEDBACK_BUFFER";
	GLEnum[GLEnum["TRANSFORM_FEEDBACK_BUFFER_BINDING"] = 35983] = "TRANSFORM_FEEDBACK_BUFFER_BINDING";
	GLEnum[GLEnum["TRANSFORM_FEEDBACK"] = 36386] = "TRANSFORM_FEEDBACK";
	GLEnum[GLEnum["TRANSFORM_FEEDBACK_PAUSED"] = 36387] = "TRANSFORM_FEEDBACK_PAUSED";
	GLEnum[GLEnum["TRANSFORM_FEEDBACK_ACTIVE"] = 36388] = "TRANSFORM_FEEDBACK_ACTIVE";
	GLEnum[GLEnum["TRANSFORM_FEEDBACK_BINDING"] = 36389] = "TRANSFORM_FEEDBACK_BINDING";
	GLEnum[GLEnum["FRAMEBUFFER_ATTACHMENT_COLOR_ENCODING"] = 33296] = "FRAMEBUFFER_ATTACHMENT_COLOR_ENCODING";
	GLEnum[GLEnum["FRAMEBUFFER_ATTACHMENT_COMPONENT_TYPE"] = 33297] = "FRAMEBUFFER_ATTACHMENT_COMPONENT_TYPE";
	GLEnum[GLEnum["FRAMEBUFFER_ATTACHMENT_RED_SIZE"] = 33298] = "FRAMEBUFFER_ATTACHMENT_RED_SIZE";
	GLEnum[GLEnum["FRAMEBUFFER_ATTACHMENT_GREEN_SIZE"] = 33299] = "FRAMEBUFFER_ATTACHMENT_GREEN_SIZE";
	GLEnum[GLEnum["FRAMEBUFFER_ATTACHMENT_BLUE_SIZE"] = 33300] = "FRAMEBUFFER_ATTACHMENT_BLUE_SIZE";
	GLEnum[GLEnum["FRAMEBUFFER_ATTACHMENT_ALPHA_SIZE"] = 33301] = "FRAMEBUFFER_ATTACHMENT_ALPHA_SIZE";
	GLEnum[GLEnum["FRAMEBUFFER_ATTACHMENT_DEPTH_SIZE"] = 33302] = "FRAMEBUFFER_ATTACHMENT_DEPTH_SIZE";
	GLEnum[GLEnum["FRAMEBUFFER_ATTACHMENT_STENCIL_SIZE"] = 33303] = "FRAMEBUFFER_ATTACHMENT_STENCIL_SIZE";
	GLEnum[GLEnum["FRAMEBUFFER_DEFAULT"] = 33304] = "FRAMEBUFFER_DEFAULT";
	GLEnum[GLEnum["DEPTH24_STENCIL8"] = 35056] = "DEPTH24_STENCIL8";
	GLEnum[GLEnum["DRAW_FRAMEBUFFER_BINDING"] = 36006] = "DRAW_FRAMEBUFFER_BINDING";
	GLEnum[GLEnum["READ_FRAMEBUFFER_BINDING"] = 36010] = "READ_FRAMEBUFFER_BINDING";
	GLEnum[GLEnum["RENDERBUFFER_SAMPLES"] = 36011] = "RENDERBUFFER_SAMPLES";
	GLEnum[GLEnum["FRAMEBUFFER_ATTACHMENT_TEXTURE_LAYER"] = 36052] = "FRAMEBUFFER_ATTACHMENT_TEXTURE_LAYER";
	GLEnum[GLEnum["FRAMEBUFFER_INCOMPLETE_MULTISAMPLE"] = 36182] = "FRAMEBUFFER_INCOMPLETE_MULTISAMPLE";
	GLEnum[GLEnum["UNIFORM_BUFFER"] = 35345] = "UNIFORM_BUFFER";
	GLEnum[GLEnum["UNIFORM_BUFFER_BINDING"] = 35368] = "UNIFORM_BUFFER_BINDING";
	GLEnum[GLEnum["UNIFORM_BUFFER_START"] = 35369] = "UNIFORM_BUFFER_START";
	GLEnum[GLEnum["UNIFORM_BUFFER_SIZE"] = 35370] = "UNIFORM_BUFFER_SIZE";
	GLEnum[GLEnum["MAX_VERTEX_UNIFORM_BLOCKS"] = 35371] = "MAX_VERTEX_UNIFORM_BLOCKS";
	GLEnum[GLEnum["MAX_FRAGMENT_UNIFORM_BLOCKS"] = 35373] = "MAX_FRAGMENT_UNIFORM_BLOCKS";
	GLEnum[GLEnum["MAX_COMBINED_UNIFORM_BLOCKS"] = 35374] = "MAX_COMBINED_UNIFORM_BLOCKS";
	GLEnum[GLEnum["MAX_UNIFORM_BUFFER_BINDINGS"] = 35375] = "MAX_UNIFORM_BUFFER_BINDINGS";
	GLEnum[GLEnum["MAX_UNIFORM_BLOCK_SIZE"] = 35376] = "MAX_UNIFORM_BLOCK_SIZE";
	GLEnum[GLEnum["MAX_COMBINED_VERTEX_UNIFORM_COMPONENTS"] = 35377] = "MAX_COMBINED_VERTEX_UNIFORM_COMPONENTS";
	GLEnum[GLEnum["MAX_COMBINED_FRAGMENT_UNIFORM_COMPONENTS"] = 35379] = "MAX_COMBINED_FRAGMENT_UNIFORM_COMPONENTS";
	GLEnum[GLEnum["UNIFORM_BUFFER_OFFSET_ALIGNMENT"] = 35380] = "UNIFORM_BUFFER_OFFSET_ALIGNMENT";
	GLEnum[GLEnum["ACTIVE_UNIFORM_BLOCKS"] = 35382] = "ACTIVE_UNIFORM_BLOCKS";
	GLEnum[GLEnum["UNIFORM_TYPE"] = 35383] = "UNIFORM_TYPE";
	GLEnum[GLEnum["UNIFORM_SIZE"] = 35384] = "UNIFORM_SIZE";
	GLEnum[GLEnum["UNIFORM_BLOCK_INDEX"] = 35386] = "UNIFORM_BLOCK_INDEX";
	GLEnum[GLEnum["UNIFORM_OFFSET"] = 35387] = "UNIFORM_OFFSET";
	GLEnum[GLEnum["UNIFORM_ARRAY_STRIDE"] = 35388] = "UNIFORM_ARRAY_STRIDE";
	GLEnum[GLEnum["UNIFORM_MATRIX_STRIDE"] = 35389] = "UNIFORM_MATRIX_STRIDE";
	GLEnum[GLEnum["UNIFORM_IS_ROW_MAJOR"] = 35390] = "UNIFORM_IS_ROW_MAJOR";
	GLEnum[GLEnum["UNIFORM_BLOCK_BINDING"] = 35391] = "UNIFORM_BLOCK_BINDING";
	GLEnum[GLEnum["UNIFORM_BLOCK_DATA_SIZE"] = 35392] = "UNIFORM_BLOCK_DATA_SIZE";
	GLEnum[GLEnum["UNIFORM_BLOCK_ACTIVE_UNIFORMS"] = 35394] = "UNIFORM_BLOCK_ACTIVE_UNIFORMS";
	GLEnum[GLEnum["UNIFORM_BLOCK_ACTIVE_UNIFORM_INDICES"] = 35395] = "UNIFORM_BLOCK_ACTIVE_UNIFORM_INDICES";
	GLEnum[GLEnum["UNIFORM_BLOCK_REFERENCED_BY_VERTEX_SHADER"] = 35396] = "UNIFORM_BLOCK_REFERENCED_BY_VERTEX_SHADER";
	GLEnum[GLEnum["UNIFORM_BLOCK_REFERENCED_BY_FRAGMENT_SHADER"] = 35398] = "UNIFORM_BLOCK_REFERENCED_BY_FRAGMENT_SHADER";
	GLEnum[GLEnum["OBJECT_TYPE"] = 37138] = "OBJECT_TYPE";
	GLEnum[GLEnum["SYNC_CONDITION"] = 37139] = "SYNC_CONDITION";
	GLEnum[GLEnum["SYNC_STATUS"] = 37140] = "SYNC_STATUS";
	GLEnum[GLEnum["SYNC_FLAGS"] = 37141] = "SYNC_FLAGS";
	GLEnum[GLEnum["SYNC_FENCE"] = 37142] = "SYNC_FENCE";
	GLEnum[GLEnum["SYNC_GPU_COMMANDS_COMPLETE"] = 37143] = "SYNC_GPU_COMMANDS_COMPLETE";
	GLEnum[GLEnum["UNSIGNALED"] = 37144] = "UNSIGNALED";
	GLEnum[GLEnum["SIGNALED"] = 37145] = "SIGNALED";
	GLEnum[GLEnum["ALREADY_SIGNALED"] = 37146] = "ALREADY_SIGNALED";
	GLEnum[GLEnum["TIMEOUT_EXPIRED"] = 37147] = "TIMEOUT_EXPIRED";
	GLEnum[GLEnum["CONDITION_SATISFIED"] = 37148] = "CONDITION_SATISFIED";
	GLEnum[GLEnum["WAIT_FAILED"] = 37149] = "WAIT_FAILED";
	GLEnum[GLEnum["SYNC_FLUSH_COMMANDS_BIT"] = 1] = "SYNC_FLUSH_COMMANDS_BIT";
	GLEnum[GLEnum["COLOR"] = 6144] = "COLOR";
	GLEnum[GLEnum["DEPTH"] = 6145] = "DEPTH";
	GLEnum[GLEnum["STENCIL"] = 6146] = "STENCIL";
	GLEnum[GLEnum["MIN"] = 32775] = "MIN";
	GLEnum[GLEnum["MAX"] = 32776] = "MAX";
	GLEnum[GLEnum["DEPTH_COMPONENT24"] = 33190] = "DEPTH_COMPONENT24";
	GLEnum[GLEnum["STREAM_READ"] = 35041] = "STREAM_READ";
	GLEnum[GLEnum["STREAM_COPY"] = 35042] = "STREAM_COPY";
	GLEnum[GLEnum["STATIC_READ"] = 35045] = "STATIC_READ";
	GLEnum[GLEnum["STATIC_COPY"] = 35046] = "STATIC_COPY";
	GLEnum[GLEnum["DYNAMIC_READ"] = 35049] = "DYNAMIC_READ";
	GLEnum[GLEnum["DYNAMIC_COPY"] = 35050] = "DYNAMIC_COPY";
	GLEnum[GLEnum["DEPTH_COMPONENT32F"] = 36012] = "DEPTH_COMPONENT32F";
	GLEnum[GLEnum["DEPTH32F_STENCIL8"] = 36013] = "DEPTH32F_STENCIL8";
	GLEnum[GLEnum["INVALID_INDEX"] = 4294967295] = "INVALID_INDEX";
	GLEnum[GLEnum["TIMEOUT_IGNORED"] = -1] = "TIMEOUT_IGNORED";
	GLEnum[GLEnum["MAX_CLIENT_WAIT_TIMEOUT_WEBGL"] = 37447] = "MAX_CLIENT_WAIT_TIMEOUT_WEBGL";
	/** Passed to getParameter to get the vendor string of the graphics driver. */
	GLEnum[GLEnum["UNMASKED_VENDOR_WEBGL"] = 37445] = "UNMASKED_VENDOR_WEBGL";
	/** Passed to getParameter to get the renderer string of the graphics driver. */
	GLEnum[GLEnum["UNMASKED_RENDERER_WEBGL"] = 37446] = "UNMASKED_RENDERER_WEBGL";
	/** Returns the maximum available anisotropy. */
	GLEnum[GLEnum["MAX_TEXTURE_MAX_ANISOTROPY_EXT"] = 34047] = "MAX_TEXTURE_MAX_ANISOTROPY_EXT";
	/** Passed to texParameter to set the desired maximum anisotropy for a texture. */
	GLEnum[GLEnum["TEXTURE_MAX_ANISOTROPY_EXT"] = 34046] = "TEXTURE_MAX_ANISOTROPY_EXT";
	GLEnum[GLEnum["R16_EXT"] = 33322] = "R16_EXT";
	GLEnum[GLEnum["RG16_EXT"] = 33324] = "RG16_EXT";
	GLEnum[GLEnum["RGB16_EXT"] = 32852] = "RGB16_EXT";
	GLEnum[GLEnum["RGBA16_EXT"] = 32859] = "RGBA16_EXT";
	GLEnum[GLEnum["R16_SNORM_EXT"] = 36760] = "R16_SNORM_EXT";
	GLEnum[GLEnum["RG16_SNORM_EXT"] = 36761] = "RG16_SNORM_EXT";
	GLEnum[GLEnum["RGB16_SNORM_EXT"] = 36762] = "RGB16_SNORM_EXT";
	GLEnum[GLEnum["RGBA16_SNORM_EXT"] = 36763] = "RGBA16_SNORM_EXT";
	/** A DXT1-compressed image in an RGB image format. */
	GLEnum[GLEnum["COMPRESSED_RGB_S3TC_DXT1_EXT"] = 33776] = "COMPRESSED_RGB_S3TC_DXT1_EXT";
	/** A DXT1-compressed image in an RGB image format with a simple on/off alpha value. */
	GLEnum[GLEnum["COMPRESSED_RGBA_S3TC_DXT1_EXT"] = 33777] = "COMPRESSED_RGBA_S3TC_DXT1_EXT";
	/** A DXT3-compressed image in an RGBA image format. Compared to a 32-bit RGBA texture, it offers 4:1 compression. */
	GLEnum[GLEnum["COMPRESSED_RGBA_S3TC_DXT3_EXT"] = 33778] = "COMPRESSED_RGBA_S3TC_DXT3_EXT";
	/** A DXT5-compressed image in an RGBA image format. It also provides a 4:1 compression, but differs to the DXT3 compression in how the alpha compression is done. */
	GLEnum[GLEnum["COMPRESSED_RGBA_S3TC_DXT5_EXT"] = 33779] = "COMPRESSED_RGBA_S3TC_DXT5_EXT";
	GLEnum[GLEnum["COMPRESSED_SRGB_S3TC_DXT1_EXT"] = 35916] = "COMPRESSED_SRGB_S3TC_DXT1_EXT";
	GLEnum[GLEnum["COMPRESSED_SRGB_ALPHA_S3TC_DXT1_EXT"] = 35917] = "COMPRESSED_SRGB_ALPHA_S3TC_DXT1_EXT";
	GLEnum[GLEnum["COMPRESSED_SRGB_ALPHA_S3TC_DXT3_EXT"] = 35918] = "COMPRESSED_SRGB_ALPHA_S3TC_DXT3_EXT";
	GLEnum[GLEnum["COMPRESSED_SRGB_ALPHA_S3TC_DXT5_EXT"] = 35919] = "COMPRESSED_SRGB_ALPHA_S3TC_DXT5_EXT";
	GLEnum[GLEnum["COMPRESSED_RED_RGTC1_EXT"] = 36283] = "COMPRESSED_RED_RGTC1_EXT";
	GLEnum[GLEnum["COMPRESSED_SIGNED_RED_RGTC1_EXT"] = 36284] = "COMPRESSED_SIGNED_RED_RGTC1_EXT";
	GLEnum[GLEnum["COMPRESSED_RED_GREEN_RGTC2_EXT"] = 36285] = "COMPRESSED_RED_GREEN_RGTC2_EXT";
	GLEnum[GLEnum["COMPRESSED_SIGNED_RED_GREEN_RGTC2_EXT"] = 36286] = "COMPRESSED_SIGNED_RED_GREEN_RGTC2_EXT";
	GLEnum[GLEnum["COMPRESSED_RGBA_BPTC_UNORM_EXT"] = 36492] = "COMPRESSED_RGBA_BPTC_UNORM_EXT";
	GLEnum[GLEnum["COMPRESSED_SRGB_ALPHA_BPTC_UNORM_EXT"] = 36493] = "COMPRESSED_SRGB_ALPHA_BPTC_UNORM_EXT";
	GLEnum[GLEnum["COMPRESSED_RGB_BPTC_SIGNED_FLOAT_EXT"] = 36494] = "COMPRESSED_RGB_BPTC_SIGNED_FLOAT_EXT";
	GLEnum[GLEnum["COMPRESSED_RGB_BPTC_UNSIGNED_FLOAT_EXT"] = 36495] = "COMPRESSED_RGB_BPTC_UNSIGNED_FLOAT_EXT";
	/** One-channel (red) unsigned format compression. */
	GLEnum[GLEnum["COMPRESSED_R11_EAC"] = 37488] = "COMPRESSED_R11_EAC";
	/** One-channel (red) signed format compression. */
	GLEnum[GLEnum["COMPRESSED_SIGNED_R11_EAC"] = 37489] = "COMPRESSED_SIGNED_R11_EAC";
	/** Two-channel (red and green) unsigned format compression. */
	GLEnum[GLEnum["COMPRESSED_RG11_EAC"] = 37490] = "COMPRESSED_RG11_EAC";
	/** Two-channel (red and green) signed format compression. */
	GLEnum[GLEnum["COMPRESSED_SIGNED_RG11_EAC"] = 37491] = "COMPRESSED_SIGNED_RG11_EAC";
	/** Compresses RGB8 data with no alpha channel. */
	GLEnum[GLEnum["COMPRESSED_RGB8_ETC2"] = 37492] = "COMPRESSED_RGB8_ETC2";
	/** Compresses RGBA8 data. The RGB part is encoded the same as RGB_ETC2, but the alpha part is encoded separately. */
	GLEnum[GLEnum["COMPRESSED_RGBA8_ETC2_EAC"] = 37493] = "COMPRESSED_RGBA8_ETC2_EAC";
	/** Compresses sRGB8 data with no alpha channel. */
	GLEnum[GLEnum["COMPRESSED_SRGB8_ETC2"] = 37494] = "COMPRESSED_SRGB8_ETC2";
	/** Compresses sRGBA8 data. The sRGB part is encoded the same as SRGB_ETC2, but the alpha part is encoded separately. */
	GLEnum[GLEnum["COMPRESSED_SRGB8_ALPHA8_ETC2_EAC"] = 37495] = "COMPRESSED_SRGB8_ALPHA8_ETC2_EAC";
	/** Similar to RGB8_ETC, but with ability to punch through the alpha channel, which means to make it completely opaque or transparent. */
	GLEnum[GLEnum["COMPRESSED_RGB8_PUNCHTHROUGH_ALPHA1_ETC2"] = 37496] = "COMPRESSED_RGB8_PUNCHTHROUGH_ALPHA1_ETC2";
	/** Similar to SRGB8_ETC, but with ability to punch through the alpha channel, which means to make it completely opaque or transparent. */
	GLEnum[GLEnum["COMPRESSED_SRGB8_PUNCHTHROUGH_ALPHA1_ETC2"] = 37497] = "COMPRESSED_SRGB8_PUNCHTHROUGH_ALPHA1_ETC2";
	/** RGB compression in 4-bit mode. One block for each 4×4 pixels. */
	GLEnum[GLEnum["COMPRESSED_RGB_PVRTC_4BPPV1_IMG"] = 35840] = "COMPRESSED_RGB_PVRTC_4BPPV1_IMG";
	/** RGBA compression in 4-bit mode. One block for each 4×4 pixels. */
	GLEnum[GLEnum["COMPRESSED_RGBA_PVRTC_4BPPV1_IMG"] = 35842] = "COMPRESSED_RGBA_PVRTC_4BPPV1_IMG";
	/** RGB compression in 2-bit mode. One block for each 8×4 pixels. */
	GLEnum[GLEnum["COMPRESSED_RGB_PVRTC_2BPPV1_IMG"] = 35841] = "COMPRESSED_RGB_PVRTC_2BPPV1_IMG";
	/** RGBA compression in 2-bit mode. One block for each 8×4 pixels. */
	GLEnum[GLEnum["COMPRESSED_RGBA_PVRTC_2BPPV1_IMG"] = 35843] = "COMPRESSED_RGBA_PVRTC_2BPPV1_IMG";
	/** Compresses 24-bit RGB data with no alpha channel. */
	GLEnum[GLEnum["COMPRESSED_RGB_ETC1_WEBGL"] = 36196] = "COMPRESSED_RGB_ETC1_WEBGL";
	GLEnum[GLEnum["COMPRESSED_RGB_ATC_WEBGL"] = 35986] = "COMPRESSED_RGB_ATC_WEBGL";
	GLEnum[GLEnum["COMPRESSED_RGBA_ATC_EXPLICIT_ALPHA_WEBGL"] = 35986] = "COMPRESSED_RGBA_ATC_EXPLICIT_ALPHA_WEBGL";
	GLEnum[GLEnum["COMPRESSED_RGBA_ATC_INTERPOLATED_ALPHA_WEBGL"] = 34798] = "COMPRESSED_RGBA_ATC_INTERPOLATED_ALPHA_WEBGL";
	GLEnum[GLEnum["COMPRESSED_RGBA_ASTC_4x4_KHR"] = 37808] = "COMPRESSED_RGBA_ASTC_4x4_KHR";
	GLEnum[GLEnum["COMPRESSED_RGBA_ASTC_5x4_KHR"] = 37809] = "COMPRESSED_RGBA_ASTC_5x4_KHR";
	GLEnum[GLEnum["COMPRESSED_RGBA_ASTC_5x5_KHR"] = 37810] = "COMPRESSED_RGBA_ASTC_5x5_KHR";
	GLEnum[GLEnum["COMPRESSED_RGBA_ASTC_6x5_KHR"] = 37811] = "COMPRESSED_RGBA_ASTC_6x5_KHR";
	GLEnum[GLEnum["COMPRESSED_RGBA_ASTC_6x6_KHR"] = 37812] = "COMPRESSED_RGBA_ASTC_6x6_KHR";
	GLEnum[GLEnum["COMPRESSED_RGBA_ASTC_8x5_KHR"] = 37813] = "COMPRESSED_RGBA_ASTC_8x5_KHR";
	GLEnum[GLEnum["COMPRESSED_RGBA_ASTC_8x6_KHR"] = 37814] = "COMPRESSED_RGBA_ASTC_8x6_KHR";
	GLEnum[GLEnum["COMPRESSED_RGBA_ASTC_8x8_KHR"] = 37815] = "COMPRESSED_RGBA_ASTC_8x8_KHR";
	GLEnum[GLEnum["COMPRESSED_RGBA_ASTC_10x5_KHR"] = 37816] = "COMPRESSED_RGBA_ASTC_10x5_KHR";
	GLEnum[GLEnum["COMPRESSED_RGBA_ASTC_10x6_KHR"] = 37817] = "COMPRESSED_RGBA_ASTC_10x6_KHR";
	GLEnum[GLEnum["COMPRESSED_RGBA_ASTC_10x8_KHR"] = 37818] = "COMPRESSED_RGBA_ASTC_10x8_KHR";
	GLEnum[GLEnum["COMPRESSED_RGBA_ASTC_10x10_KHR"] = 37819] = "COMPRESSED_RGBA_ASTC_10x10_KHR";
	GLEnum[GLEnum["COMPRESSED_RGBA_ASTC_12x10_KHR"] = 37820] = "COMPRESSED_RGBA_ASTC_12x10_KHR";
	GLEnum[GLEnum["COMPRESSED_RGBA_ASTC_12x12_KHR"] = 37821] = "COMPRESSED_RGBA_ASTC_12x12_KHR";
	GLEnum[GLEnum["COMPRESSED_SRGB8_ALPHA8_ASTC_4x4_KHR"] = 37840] = "COMPRESSED_SRGB8_ALPHA8_ASTC_4x4_KHR";
	GLEnum[GLEnum["COMPRESSED_SRGB8_ALPHA8_ASTC_5x4_KHR"] = 37841] = "COMPRESSED_SRGB8_ALPHA8_ASTC_5x4_KHR";
	GLEnum[GLEnum["COMPRESSED_SRGB8_ALPHA8_ASTC_5x5_KHR"] = 37842] = "COMPRESSED_SRGB8_ALPHA8_ASTC_5x5_KHR";
	GLEnum[GLEnum["COMPRESSED_SRGB8_ALPHA8_ASTC_6x5_KHR"] = 37843] = "COMPRESSED_SRGB8_ALPHA8_ASTC_6x5_KHR";
	GLEnum[GLEnum["COMPRESSED_SRGB8_ALPHA8_ASTC_6x6_KHR"] = 37844] = "COMPRESSED_SRGB8_ALPHA8_ASTC_6x6_KHR";
	GLEnum[GLEnum["COMPRESSED_SRGB8_ALPHA8_ASTC_8x5_KHR"] = 37845] = "COMPRESSED_SRGB8_ALPHA8_ASTC_8x5_KHR";
	GLEnum[GLEnum["COMPRESSED_SRGB8_ALPHA8_ASTC_8x6_KHR"] = 37846] = "COMPRESSED_SRGB8_ALPHA8_ASTC_8x6_KHR";
	GLEnum[GLEnum["COMPRESSED_SRGB8_ALPHA8_ASTC_8x8_KHR"] = 37847] = "COMPRESSED_SRGB8_ALPHA8_ASTC_8x8_KHR";
	GLEnum[GLEnum["COMPRESSED_SRGB8_ALPHA8_ASTC_10x5_KHR"] = 37848] = "COMPRESSED_SRGB8_ALPHA8_ASTC_10x5_KHR";
	GLEnum[GLEnum["COMPRESSED_SRGB8_ALPHA8_ASTC_10x6_KHR"] = 37849] = "COMPRESSED_SRGB8_ALPHA8_ASTC_10x6_KHR";
	GLEnum[GLEnum["COMPRESSED_SRGB8_ALPHA8_ASTC_10x8_KHR"] = 37850] = "COMPRESSED_SRGB8_ALPHA8_ASTC_10x8_KHR";
	GLEnum[GLEnum["COMPRESSED_SRGB8_ALPHA8_ASTC_10x10_KHR"] = 37851] = "COMPRESSED_SRGB8_ALPHA8_ASTC_10x10_KHR";
	GLEnum[GLEnum["COMPRESSED_SRGB8_ALPHA8_ASTC_12x10_KHR"] = 37852] = "COMPRESSED_SRGB8_ALPHA8_ASTC_12x10_KHR";
	GLEnum[GLEnum["COMPRESSED_SRGB8_ALPHA8_ASTC_12x12_KHR"] = 37853] = "COMPRESSED_SRGB8_ALPHA8_ASTC_12x12_KHR";
	/** The number of bits used to hold the query result for the given target. */
	GLEnum[GLEnum["QUERY_COUNTER_BITS_EXT"] = 34916] = "QUERY_COUNTER_BITS_EXT";
	/** The currently active query. */
	GLEnum[GLEnum["CURRENT_QUERY_EXT"] = 34917] = "CURRENT_QUERY_EXT";
	/** The query result. */
	GLEnum[GLEnum["QUERY_RESULT_EXT"] = 34918] = "QUERY_RESULT_EXT";
	/** A Boolean indicating whether or not a query result is available. */
	GLEnum[GLEnum["QUERY_RESULT_AVAILABLE_EXT"] = 34919] = "QUERY_RESULT_AVAILABLE_EXT";
	/** Elapsed time (in nanoseconds). */
	GLEnum[GLEnum["TIME_ELAPSED_EXT"] = 35007] = "TIME_ELAPSED_EXT";
	/** The current time. */
	GLEnum[GLEnum["TIMESTAMP_EXT"] = 36392] = "TIMESTAMP_EXT";
	/** A Boolean indicating whether or not the GPU performed any disjoint operation (lost context) */
	GLEnum[GLEnum["GPU_DISJOINT_EXT"] = 36795] = "GPU_DISJOINT_EXT";
	/** a non-blocking poll operation, so that compile/link status availability can be queried without potentially incurring stalls */
	GLEnum[GLEnum["COMPLETION_STATUS_KHR"] = 37297] = "COMPLETION_STATUS_KHR";
	/** Disables depth clipping */
	GLEnum[GLEnum["DEPTH_CLAMP_EXT"] = 34383] = "DEPTH_CLAMP_EXT";
	/** Values of first vertex in primitive are used for flat shading */
	GLEnum[GLEnum["FIRST_VERTEX_CONVENTION_WEBGL"] = 36429] = "FIRST_VERTEX_CONVENTION_WEBGL";
	/** Values of first vertex in primitive are used for flat shading */
	GLEnum[GLEnum["LAST_VERTEX_CONVENTION_WEBGL"] = 36430] = "LAST_VERTEX_CONVENTION_WEBGL";
	/** Controls which vertex in primitive is used for flat shading */
	GLEnum[GLEnum["PROVOKING_VERTEX_WEBL"] = 36431] = "PROVOKING_VERTEX_WEBL";
	GLEnum[GLEnum["POLYGON_MODE_WEBGL"] = 2880] = "POLYGON_MODE_WEBGL";
	GLEnum[GLEnum["POLYGON_OFFSET_LINE_WEBGL"] = 10754] = "POLYGON_OFFSET_LINE_WEBGL";
	GLEnum[GLEnum["LINE_WEBGL"] = 6913] = "LINE_WEBGL";
	GLEnum[GLEnum["FILL_WEBGL"] = 6914] = "FILL_WEBGL";
	/** Max clip distances */
	GLEnum[GLEnum["MAX_CLIP_DISTANCES_WEBGL"] = 3378] = "MAX_CLIP_DISTANCES_WEBGL";
	/** Max cull distances */
	GLEnum[GLEnum["MAX_CULL_DISTANCES_WEBGL"] = 33529] = "MAX_CULL_DISTANCES_WEBGL";
	/** Max clip and cull distances */
	GLEnum[GLEnum["MAX_COMBINED_CLIP_AND_CULL_DISTANCES_WEBGL"] = 33530] = "MAX_COMBINED_CLIP_AND_CULL_DISTANCES_WEBGL";
	/** Enable gl_ClipDistance[0] and gl_CullDistance[0] */
	GLEnum[GLEnum["CLIP_DISTANCE0_WEBGL"] = 12288] = "CLIP_DISTANCE0_WEBGL";
	/** Enable gl_ClipDistance[1] and gl_CullDistance[1] */
	GLEnum[GLEnum["CLIP_DISTANCE1_WEBGL"] = 12289] = "CLIP_DISTANCE1_WEBGL";
	/** Enable gl_ClipDistance[2] and gl_CullDistance[2] */
	GLEnum[GLEnum["CLIP_DISTANCE2_WEBGL"] = 12290] = "CLIP_DISTANCE2_WEBGL";
	/** Enable gl_ClipDistance[3] and gl_CullDistance[3] */
	GLEnum[GLEnum["CLIP_DISTANCE3_WEBGL"] = 12291] = "CLIP_DISTANCE3_WEBGL";
	/** Enable gl_ClipDistance[4] and gl_CullDistance[4] */
	GLEnum[GLEnum["CLIP_DISTANCE4_WEBGL"] = 12292] = "CLIP_DISTANCE4_WEBGL";
	/** Enable gl_ClipDistance[5] and gl_CullDistance[5] */
	GLEnum[GLEnum["CLIP_DISTANCE5_WEBGL"] = 12293] = "CLIP_DISTANCE5_WEBGL";
	/** Enable gl_ClipDistance[6] and gl_CullDistance[6] */
	GLEnum[GLEnum["CLIP_DISTANCE6_WEBGL"] = 12294] = "CLIP_DISTANCE6_WEBGL";
	/** Enable gl_ClipDistance[7] and gl_CullDistance[7] */
	GLEnum[GLEnum["CLIP_DISTANCE7_WEBGL"] = 12295] = "CLIP_DISTANCE7_WEBGL";
	/** EXT_polygon_offset_clamp https://registry.khronos.org/webgl/extensions/EXT_polygon_offset_clamp/ */
	GLEnum[GLEnum["POLYGON_OFFSET_CLAMP_EXT"] = 36379] = "POLYGON_OFFSET_CLAMP_EXT";
	/** EXT_clip_control https://registry.khronos.org/webgl/extensions/EXT_clip_control/ */
	GLEnum[GLEnum["LOWER_LEFT_EXT"] = 36001] = "LOWER_LEFT_EXT";
	GLEnum[GLEnum["UPPER_LEFT_EXT"] = 36002] = "UPPER_LEFT_EXT";
	GLEnum[GLEnum["NEGATIVE_ONE_TO_ONE_EXT"] = 37726] = "NEGATIVE_ONE_TO_ONE_EXT";
	GLEnum[GLEnum["ZERO_TO_ONE_EXT"] = 37727] = "ZERO_TO_ONE_EXT";
	GLEnum[GLEnum["CLIP_ORIGIN_EXT"] = 37724] = "CLIP_ORIGIN_EXT";
	GLEnum[GLEnum["CLIP_DEPTH_MODE_EXT"] = 37725] = "CLIP_DEPTH_MODE_EXT";
	/** WEBGL_blend_func_extended https://registry.khronos.org/webgl/extensions/WEBGL_blend_func_extended/ */
	GLEnum[GLEnum["SRC1_COLOR_WEBGL"] = 35065] = "SRC1_COLOR_WEBGL";
	GLEnum[GLEnum["SRC1_ALPHA_WEBGL"] = 34185] = "SRC1_ALPHA_WEBGL";
	GLEnum[GLEnum["ONE_MINUS_SRC1_COLOR_WEBGL"] = 35066] = "ONE_MINUS_SRC1_COLOR_WEBGL";
	GLEnum[GLEnum["ONE_MINUS_SRC1_ALPHA_WEBGL"] = 35067] = "ONE_MINUS_SRC1_ALPHA_WEBGL";
	GLEnum[GLEnum["MAX_DUAL_SOURCE_DRAW_BUFFERS_WEBGL"] = 35068] = "MAX_DUAL_SOURCE_DRAW_BUFFERS_WEBGL";
	/** EXT_texture_mirror_clamp_to_edge https://registry.khronos.org/webgl/extensions/EXT_texture_mirror_clamp_to_edge/ */
	GLEnum[GLEnum["MIRROR_CLAMP_TO_EDGE_EXT"] = 34627] = "MIRROR_CLAMP_TO_EDGE_EXT";
})(GLEnum || (GLEnum = {}));
//#endregion
//#region node_modules/@luma.gl/webgl/dist/utils/load-script.js
/**
* Load a script (identified by an url). When the url returns, the
* content of this file is added into a new script element, attached to the DOM (body element)
* @param scriptUrl defines the url of the script to laod
* @param scriptId defines the id of the script element
*/
async function loadScript(scriptUrl, scriptId) {
	const head = document.getElementsByTagName("head")[0];
	if (!head) throw new Error("loadScript");
	const script = document.createElement("script");
	script.setAttribute("type", "text/javascript");
	script.setAttribute("src", scriptUrl);
	if (scriptId) script.id = scriptId;
	return new Promise((resolve, reject) => {
		script.onload = resolve;
		script.onerror = (error) => reject(/* @__PURE__ */ new Error(`Unable to load script '${scriptUrl}': ${error}`));
		head.appendChild(script);
	});
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/context/helpers/webgl-context-data.js
/**
* Gets luma.gl specific state from a context
* @returns context state
*/
function getWebGLContextData$1(gl) {
	const contextData = gl.luma || {
		_polyfilled: false,
		extensions: {},
		softwareRenderer: false
	};
	contextData._polyfilled ??= false;
	contextData.extensions ||= {};
	gl.luma = contextData;
	return contextData;
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/context/debug/spector.js
var LOG_LEVEL = 1;
var spector = null;
var initialized = false;
var DEFAULT_SPECTOR_PROPS = {
	debugSpectorJS: log.get("debug-spectorjs"),
	debugSpectorJSUrl: "https://cdn.jsdelivr.net/npm/spectorjs@0.9.30/dist/spector.bundle.js",
	gl: void 0
};
/** Loads spector from CDN if not already installed */
async function loadSpectorJS(props) {
	if (!globalThis.SPECTOR) try {
		await loadScript(props.debugSpectorJSUrl || DEFAULT_SPECTOR_PROPS.debugSpectorJSUrl);
	} catch (error) {
		log.warn(String(error));
	}
}
function initializeSpectorJS(props) {
	props = {
		...DEFAULT_SPECTOR_PROPS,
		...props
	};
	if (!props.debugSpectorJS) return null;
	if (!spector && globalThis.SPECTOR && !globalThis.luma?.spector) {
		log.probe(LOG_LEVEL, "SPECTOR found and initialized. Start with `luma.spector.displayUI()`")();
		const { Spector: SpectorJS } = globalThis.SPECTOR;
		spector = new SpectorJS();
		if (globalThis.luma) globalThis.luma.spector = spector;
	}
	if (!spector) return null;
	if (!initialized) {
		initialized = true;
		spector.spyCanvases();
		spector?.onCaptureStarted.add((capture) => log.info("Spector capture started:", capture)());
		spector?.onCapture.add((capture) => {
			log.info("Spector capture complete:", capture)();
			spector?.getResultUI();
			spector?.resultView.display();
			spector?.resultView.addCapture(capture);
		});
	}
	if (props.gl) {
		const gl = props.gl;
		const contextData = getWebGLContextData$1(gl);
		const device = contextData.device;
		spector?.startCapture(props.gl, 500);
		contextData.device = device;
		new Promise((resolve) => setTimeout(resolve, 2e3)).then((_) => {
			log.info("Spector capture stopped after 2 seconds")();
			spector?.stopCapture();
		});
	}
	return spector;
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/context/debug/webgl-developer-tools.js
var WEBGL_DEBUG_CDN_URL = "https://unpkg.com/webgl-debug@2.0.1/index.js";
function getWebGLContextData(gl) {
	gl.luma = gl.luma || {};
	return gl.luma;
}
/**
* Loads Khronos WebGLDeveloperTools from CDN if not already installed
* const WebGLDebugUtils = require('webgl-debug');
* @see https://github.com/KhronosGroup/WebGLDeveloperTools
* @see https://github.com/vorg/webgl-debug
*/
async function loadWebGLDeveloperTools() {
	if (isBrowser$1() && !globalThis.WebGLDebugUtils) {
		globalThis.global = globalThis.global || globalThis;
		globalThis.global.module = {};
		await loadScript(WEBGL_DEBUG_CDN_URL);
	}
}
function makeDebugContext(gl, props = {}) {
	return props.debugWebGL || props.traceWebGL ? getDebugContext(gl, props) : getRealContext(gl);
}
function getRealContext(gl) {
	const data = getWebGLContextData(gl);
	return data.realContext ? data.realContext : gl;
}
function getDebugContext(gl, props) {
	if (!globalThis.WebGLDebugUtils) {
		log.warn("webgl-debug not loaded")();
		return gl;
	}
	const data = getWebGLContextData(gl);
	if (data.debugContext) return data.debugContext;
	globalThis.WebGLDebugUtils.init({
		...GLEnum,
		...gl
	});
	const glDebug = globalThis.WebGLDebugUtils.makeDebugContext(gl, onGLError.bind(null, props), onValidateGLFunc.bind(null, props));
	for (const key in GLEnum) if (!(key in glDebug) && typeof GLEnum[key] === "number") glDebug[key] = GLEnum[key];
	class WebGLDebugContext {}
	Object.setPrototypeOf(glDebug, Object.getPrototypeOf(gl));
	Object.setPrototypeOf(WebGLDebugContext, glDebug);
	const debugContext = Object.create(WebGLDebugContext);
	data.realContext = gl;
	data.debugContext = debugContext;
	debugContext.luma = data;
	debugContext.debug = true;
	return debugContext;
}
function getFunctionString(functionName, functionArgs) {
	functionArgs = Array.from(functionArgs).map((arg) => arg === void 0 ? "undefined" : arg);
	let args = globalThis.WebGLDebugUtils.glFunctionArgsToString(functionName, functionArgs);
	args = `${args.slice(0, 100)}${args.length > 100 ? "..." : ""}`;
	return `gl.${functionName}(${args})`;
}
function onGLError(props, err, functionName, args) {
	args = Array.from(args).map((arg) => arg === void 0 ? "undefined" : arg);
	const message = `${globalThis.WebGLDebugUtils.glEnumToString(err)} in gl.${functionName}(${globalThis.WebGLDebugUtils.glFunctionArgsToString(functionName, args)})`;
	log.error("%cWebGL", "color: white; background: red; padding: 2px 6px; border-radius: 3px;", message)();
	debugger;
	throw new Error(message);
}
function onValidateGLFunc(props, functionName, functionArgs) {
	let functionString = "";
	if (props.traceWebGL && log.level >= 1) {
		functionString = getFunctionString(functionName, functionArgs);
		log.info(1, "%cWebGL", "color: white; background: blue; padding: 2px 6px; border-radius: 3px;", functionString)();
	}
	for (const arg of functionArgs) if (arg === void 0) {
		functionString = functionString || getFunctionString(functionName, functionArgs);
		debugger;
	}
}
//#endregion
export { isExternalImage as $, lngLatToWorld as A, assert$6 as At, EVENT_HANDLERS as B, toDoublePrecisionArray as C, defaultLogger as Ct, addMetersToLngLat as D, getBrowser as Dt, MAX_LATITUDE as E, Stats as Et, project32_default as F, geometry_default as G, RECOGNIZERS as H, project_default as I, Sampler as J, color_default as K, getOffsetOrigin as L, unitsPerMeter as M, worldToLngLat as N, altitudeToFovy as O, isBrowser$1 as Ot, worldToPixels as P, getExternalImageSize as Q, getShaderCoordinateSystem as R, mod as S, register as St, picking_default as T, registerLoaders as Tt, UNIT as U, PROJECTION_MODE as V, EventManager as W, DeviceFeatures as X, Device as Y, DeviceLimits as Z, LIFECYCLE as _, equals as _t, loadSpectorJS as a, uid as at, Viewport as b, getShaderModuleDependencies as bt, Transition as c, Matrix4 as ct, flatten as d, Vector3 as dt, textureFormatDecoder as et, ASYNC_DEFAULTS_SYMBOL as f, len as ft, DEPRECATED_PROPS_SYMBOL as g, clamp$1 as gt, COMPONENT_SYMBOL as h, sub as ht, initializeSpectorJS as i, Resource as it, pixelsToWorld as j, fovyToAltitude as k, isBrowser$2 as kt, deepEqual as l, scale as lt, ASYNC_RESOLVED_SYMBOL as m, sqrLen as mt, makeDebugContext as n, dataTypeDecoder as nt, getWebGLContextData$1 as o, log as ot, ASYNC_ORIGINAL_SYMBOL as p, lerp as pt, Texture as q, DEFAULT_SPECTOR_PROPS as r, Buffer as rt, assert as s, lumaStats as st, loadWebGLDeveloperTools as t, vertexFormatDecoder as tt, fillArray as u, transformMat4 as ut, PROP_TYPES_SYMBOL as v, lerp$2 as vt, typed_array_manager_default as w, load as wt, mergeBounds as x, debug as xt, WebMercatorViewport as y, ShaderAssembler as yt, memoize as z };

//# sourceMappingURL=webgl-developer-tools-CC6tnIIX.js.map