import { n as __exportAll } from "./chunk-B-1-B7_t.js";
import { Dt as getBrowser, J as Sampler, Ot as isBrowser, X as DeviceFeatures, Y as Device, Z as DeviceLimits, at as uid$1, et as textureFormatDecoder, i as initializeSpectorJS, it as Resource, n as makeDebugContext, nt as dataTypeDecoder, o as getWebGLContextData, ot as log, q as Texture, rt as Buffer, tt as vertexFormatDecoder } from "./webgl-developer-tools-CC6tnIIX.js";
//#region node_modules/@luma.gl/core/dist/adapter/canvas-observer.js
/**
* Internal DOM observer orchestration for HTML canvas surfaces.
*
* @remarks
* CanvasSurface owns the tracked state and device callback dispatch. This helper only manages
* browser observers, timers, and polling loops, then reports events through callbacks.
*/
var CanvasObserver = class {
	/** Observer options and event callbacks. */
	props;
	_resizeObserver;
	_intersectionObserver;
	_observeDevicePixelRatioTimeout = null;
	_observeDevicePixelRatioMediaQuery = null;
	_handleDevicePixelRatioChange = () => this._refreshDevicePixelRatio();
	_trackPositionInterval = null;
	_started = false;
	/** Whether the DOM observers and polling loops have been started. */
	get started() {
		return this._started;
	}
	/**
	* Creates an observer coordinator for one HTML canvas.
	*
	* @param props - Observer options and event callbacks.
	*/
	constructor(props) {
		this.props = props;
	}
	/** Starts DOM observation and optional position polling. */
	start() {
		if (this._started || !this.props.canvas) return;
		this._started = true;
		this._intersectionObserver ||= new IntersectionObserver((entries) => this.props.onIntersection(entries));
		this._resizeObserver ||= new ResizeObserver((entries) => this.props.onResize(entries));
		this._intersectionObserver.observe(this.props.canvas);
		const box = this.props.resizeObserverBox;
		try {
			this._resizeObserver.observe(this.props.canvas, { box });
		} catch {
			this._resizeObserver.observe(this.props.canvas, { box: "content-box" });
		}
		this._observeDevicePixelRatioTimeout = setTimeout(() => this._refreshDevicePixelRatio(), 0);
		if (this.props.trackPosition) this._trackPosition();
	}
	/** Stops DOM observation, media-query listeners, and position polling. */
	stop() {
		if (!this._started) return;
		this._started = false;
		if (this._observeDevicePixelRatioTimeout) {
			clearTimeout(this._observeDevicePixelRatioTimeout);
			this._observeDevicePixelRatioTimeout = null;
		}
		if (this._observeDevicePixelRatioMediaQuery) {
			this._observeDevicePixelRatioMediaQuery.removeEventListener("change", this._handleDevicePixelRatioChange);
			this._observeDevicePixelRatioMediaQuery = null;
		}
		if (this._trackPositionInterval) {
			clearInterval(this._trackPositionInterval);
			this._trackPositionInterval = null;
		}
		this._resizeObserver?.disconnect();
		this._intersectionObserver?.disconnect();
	}
	/** Reports the current device pixel ratio and arms the media query for its next change. */
	_refreshDevicePixelRatio() {
		if (!this._started) return;
		this.props.onDevicePixelRatioChange();
		this._observeDevicePixelRatioMediaQuery?.removeEventListener("change", this._handleDevicePixelRatioChange);
		this._observeDevicePixelRatioMediaQuery = matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`);
		this._observeDevicePixelRatioMediaQuery.addEventListener("change", this._handleDevicePixelRatioChange, { once: true });
	}
	/**
	* Starts periodic position callbacks while the observer remains active.
	*
	* @param intervalMs - Poll interval in milliseconds.
	*/
	_trackPosition(intervalMs = 100) {
		if (this._trackPositionInterval) return;
		this._trackPositionInterval = setInterval(() => {
			if (!this._started) {
				if (this._trackPositionInterval) {
					clearInterval(this._trackPositionInterval);
					this._trackPositionInterval = null;
				}
			} else this.props.onPositionChange();
		}, intervalMs);
	}
};
//#endregion
//#region node_modules/@luma.gl/core/dist/utils/promise-utils.js
function withResolvers() {
	let resolve;
	let reject;
	return {
		promise: new Promise((_resolve, _reject) => {
			resolve = _resolve;
			reject = _reject;
		}),
		resolve,
		reject
	};
}
//#endregion
//#region node_modules/@luma.gl/core/dist/utils/assert.js
/** Throws if condition is true and narrows type */
function assert(condition, message) {
	if (!condition) {
		const error = new Error(message ?? "luma.gl assertion failed.");
		Error.captureStackTrace?.(error, assert);
		throw error;
	}
}
/** Throws if value is not defined, narrows type */
function assertDefined(value, message) {
	assert(value, message);
	return value;
}
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/canvas-surface.js
/**
* Shared tracked-canvas lifecycle used by both renderable and presentation contexts.
* - Creates a new canvas or looks up a canvas from the DOM
* - Provides check for DOM loaded
* @todo commit() @see https://github.com/w3ctag/design-reviews/issues/288
* @todo transferControlToOffscreen: @see https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/transferControlToOffscreen
*/
var CanvasSurface = class CanvasSurface {
	static isHTMLCanvas(canvas) {
		return typeof HTMLCanvasElement !== "undefined" && canvas instanceof HTMLCanvasElement;
	}
	static isOffscreenCanvas(canvas) {
		return typeof OffscreenCanvas !== "undefined" && canvas instanceof OffscreenCanvas;
	}
	static defaultProps = {
		id: void 0,
		canvas: null,
		width: 800,
		height: 600,
		useDevicePixels: true,
		pixelSizeSource: "exact",
		autoResize: true,
		container: null,
		visible: true,
		alphaMode: "opaque",
		colorSpace: "srgb",
		trackPosition: false
	};
	id;
	props;
	canvas;
	/** Handle to HTML canvas */
	htmlCanvas;
	/** Handle to wrapped OffScreenCanvas */
	offscreenCanvas;
	type;
	/** Promise that resolved once the resize observer has updated the pixel size */
	initialized;
	isInitialized = false;
	/** Visibility is automatically updated (via an IntersectionObserver) */
	isVisible = true;
	/** Width of canvas in CSS units (tracked by a ResizeObserver) */
	cssWidth;
	/** Height of canvas in CSS units (tracked by a ResizeObserver) */
	cssHeight;
	/** Device pixel ratio. Automatically updated via media queries */
	devicePixelRatio;
	/** Exact width of canvas in physical pixels (tracked by a ResizeObserver) */
	devicePixelWidth;
	/** Exact height of canvas in physical pixels (tracked by a ResizeObserver) */
	devicePixelHeight;
	/** Width of drawing buffer: automatically tracks this.pixelWidth if props.autoResize is true */
	drawingBufferWidth;
	/** Height of drawing buffer: automatically tracks this.pixelHeight if props.autoResize is true */
	drawingBufferHeight;
	/** Resolves when the canvas is initialized, i.e. when the ResizeObserver has updated the pixel size */
	_initializedResolvers = withResolvers();
	_canvasObserver;
	/** Position of the canvas in the document, updated by a timer */
	_position = [0, 0];
	/** Whether this canvas context has been destroyed */
	destroyed = false;
	/** Whether the drawing buffer size needs to be resized (deferred resizing to avoid flicker) */
	_needsDrawingBufferResize = true;
	toString() {
		return `${this[Symbol.toStringTag]}(${this.id})`;
	}
	constructor(props) {
		this.props = {
			...CanvasSurface.defaultProps,
			...props
		};
		props = this.props;
		this.initialized = this._initializedResolvers.promise;
		if (!isBrowser()) this.canvas = {
			width: props.width || 1,
			height: props.height || 1
		};
		else if (!props.canvas) this.canvas = createCanvasElement(props);
		else if (typeof props.canvas === "string") this.canvas = getCanvasFromDOM(props.canvas);
		else this.canvas = props.canvas;
		if (CanvasSurface.isHTMLCanvas(this.canvas)) {
			this.id = props.id || this.canvas.id;
			this.type = "html-canvas";
			this.htmlCanvas = this.canvas;
		} else if (CanvasSurface.isOffscreenCanvas(this.canvas)) {
			this.id = props.id || "offscreen-canvas";
			this.type = "offscreen-canvas";
			this.offscreenCanvas = this.canvas;
		} else {
			this.id = props.id || "node-canvas-context";
			this.type = "node";
		}
		this.cssWidth = this.htmlCanvas?.clientWidth || this.canvas.width;
		this.cssHeight = this.htmlCanvas?.clientHeight || this.canvas.height;
		this.devicePixelWidth = this.canvas.width;
		this.devicePixelHeight = this.canvas.height;
		this.drawingBufferWidth = this.canvas.width;
		this.drawingBufferHeight = this.canvas.height;
		this.devicePixelRatio = globalThis.devicePixelRatio || 1;
		this._position = [0, 0];
		this._canvasObserver = new CanvasObserver({
			canvas: this.htmlCanvas,
			trackPosition: this.props.trackPosition,
			resizeObserverBox: this.props.pixelSizeSource === "css-dpr" ? "content-box" : "device-pixel-content-box",
			onResize: (entries) => this._handleResize(entries),
			onIntersection: (entries) => this._handleIntersection(entries),
			onDevicePixelRatioChange: () => this._observeDevicePixelRatio(),
			onPositionChange: () => this.updatePosition()
		});
	}
	destroy() {
		if (!this.destroyed) {
			this.destroyed = true;
			this._stopObservers();
			this.device = null;
		}
	}
	setProps(props) {
		if ("useDevicePixels" in props) {
			this.props.useDevicePixels = props.useDevicePixels || false;
			this._updateDrawingBufferSize();
		}
		return this;
	}
	/** Returns a framebuffer with properly resized current 'swap chain' textures */
	getCurrentFramebuffer(options) {
		this._resizeDrawingBufferIfNeeded();
		return this._getCurrentFramebuffer(options);
	}
	getCSSSize() {
		return [this.cssWidth, this.cssHeight];
	}
	getPosition() {
		return this._position;
	}
	getDevicePixelSize() {
		return [this.devicePixelWidth, this.devicePixelHeight];
	}
	getDrawingBufferSize() {
		return [this.drawingBufferWidth, this.drawingBufferHeight];
	}
	getMaxDrawingBufferSize() {
		const maxTextureDimension = this.device.limits.maxTextureDimension2D;
		return [maxTextureDimension, maxTextureDimension];
	}
	setDrawingBufferSize(width, height) {
		width = Math.floor(width);
		height = Math.floor(height);
		if (this.drawingBufferWidth === width && this.drawingBufferHeight === height) return;
		this.drawingBufferWidth = width;
		this.drawingBufferHeight = height;
		this._needsDrawingBufferResize = true;
	}
	getDevicePixelRatio() {
		return typeof window !== "undefined" && window.devicePixelRatio || 1;
	}
	cssToDevicePixels(cssPixel, yInvert = true) {
		const ratio = this.cssToDeviceRatio();
		const [width, height] = this.getDrawingBufferSize();
		return scalePixels(cssPixel, ratio, width, height, yInvert);
	}
	/** @deprecated - use .getDevicePixelSize() */
	getPixelSize() {
		return this.getDevicePixelSize();
	}
	/** @deprecated Use the current drawing buffer size for projection setup. */
	getAspect() {
		const [width, height] = this.getDrawingBufferSize();
		return width > 0 && height > 0 ? width / height : 1;
	}
	/** @deprecated Returns multiplier need to convert CSS size to Device size */
	cssToDeviceRatio() {
		try {
			const [drawingBufferWidth] = this.getDrawingBufferSize();
			const [cssWidth] = this.getCSSSize();
			return cssWidth ? drawingBufferWidth / cssWidth : 1;
		} catch {
			return 1;
		}
	}
	/** @deprecated Use canvasContext.setDrawingBufferSize() */
	resize(size) {
		this.setDrawingBufferSize(size.width, size.height);
	}
	_setAutoCreatedCanvasId(id) {
		if (this.htmlCanvas?.id === "lumagl-auto-created-canvas") this.htmlCanvas.id = id;
	}
	/**
	* Starts DOM observation after the derived context and its device are fully initialized.
	*
	* `CanvasSurface` construction runs before subclasses can assign `this.device`, and the
	* default WebGL canvas context is created before `WebGLDevice` has initialized `limits`,
	* `features`, and the rest of its runtime state. Deferring observer startup avoids early
	* `ResizeObserver` and DPR callbacks running against a partially initialized device.
	*/
	_startObservers() {
		if (this.destroyed) return;
		this._canvasObserver.start();
	}
	/**
	* Stops all DOM observation and timers associated with a canvas surface.
	*
	* This pairs with `_startObservers()` so teardown uses the same lifecycle whether a context is
	* explicitly destroyed, abandoned during device reuse, or temporarily has not started observing
	* yet. Centralizing shutdown here keeps resize/DPR/position watchers from surviving past the
	* lifetime of the owning device.
	*/
	_stopObservers() {
		this._canvasObserver.stop();
	}
	_handleIntersection(entries) {
		if (this.destroyed) return;
		const entry = entries.find((entry_) => entry_.target === this.canvas);
		if (!entry) return;
		const isVisible = entry.isIntersecting;
		if (this.isVisible !== isVisible) {
			this.isVisible = isVisible;
			this.device.props.onVisibilityChange(this);
		}
	}
	_handleResize(entries) {
		if (this.destroyed) return;
		const entry = entries.find((entry_) => entry_.target === this.canvas);
		if (!entry) return;
		const contentBoxSize = assertDefined(entry.contentBoxSize?.[0]);
		this.cssWidth = contentBoxSize.inlineSize;
		this.cssHeight = contentBoxSize.blockSize;
		const oldPixelSize = this.getDevicePixelSize();
		this._setDevicePixelSize(this._getDevicePixelSizeFromResizeEntry(entry));
		this._updateDrawingBufferSize();
		this.device.props.onResize(this, { oldPixelSize });
	}
	_updateDrawingBufferSize() {
		if (this.props.autoResize) if (typeof this.props.useDevicePixels === "number") {
			const devicePixelRatio = this.props.useDevicePixels;
			this.setDrawingBufferSize(this.cssWidth * devicePixelRatio, this.cssHeight * devicePixelRatio);
		} else if (this.props.useDevicePixels) this.setDrawingBufferSize(this.devicePixelWidth, this.devicePixelHeight);
		else this.setDrawingBufferSize(this.cssWidth, this.cssHeight);
		this._initializedResolvers.resolve();
		this.isInitialized = true;
		this.updatePosition();
	}
	_getDevicePixelSizeFromResizeEntry(entry) {
		const contentBoxSize = assertDefined(entry.contentBoxSize?.[0]);
		if (this.props.pixelSizeSource === "css-dpr") return this._getDevicePixelSizeFromCSSSize(contentBoxSize.inlineSize, contentBoxSize.blockSize);
		return {
			devicePixelWidth: entry.devicePixelContentBoxSize?.[0]?.inlineSize || contentBoxSize.inlineSize * devicePixelRatio,
			devicePixelHeight: entry.devicePixelContentBoxSize?.[0]?.blockSize || contentBoxSize.blockSize * devicePixelRatio
		};
	}
	_getDevicePixelSizeFromCSSSize(cssWidth, cssHeight) {
		const devicePixelRatio = this.getDevicePixelRatio();
		return {
			devicePixelWidth: Math.floor(cssWidth * devicePixelRatio),
			devicePixelHeight: Math.floor(cssHeight * devicePixelRatio)
		};
	}
	_setDevicePixelSize({ devicePixelWidth, devicePixelHeight }) {
		const [maxDevicePixelWidth, maxDevicePixelHeight] = this.getMaxDrawingBufferSize();
		this.devicePixelWidth = Math.max(1, Math.min(devicePixelWidth, maxDevicePixelWidth));
		this.devicePixelHeight = Math.max(1, Math.min(devicePixelHeight, maxDevicePixelHeight));
	}
	_resizeDrawingBufferIfNeeded() {
		if (this._needsDrawingBufferResize) {
			this._needsDrawingBufferResize = false;
			if (this.drawingBufferWidth !== this.canvas.width || this.drawingBufferHeight !== this.canvas.height) {
				this.canvas.width = this.drawingBufferWidth;
				this.canvas.height = this.drawingBufferHeight;
				this._configureDevice();
			}
		}
	}
	_observeDevicePixelRatio() {
		if (this.destroyed || !this._canvasObserver.started) return;
		const oldRatio = this.devicePixelRatio;
		this.devicePixelRatio = window.devicePixelRatio;
		if (this.props.pixelSizeSource === "css-dpr") {
			const oldPixelSize = this.getDevicePixelSize();
			this._setDevicePixelSize(this._getDevicePixelSizeFromCSSSize(this.cssWidth, this.cssHeight));
			this._updateDrawingBufferSize();
			this.device.props.onResize(this, { oldPixelSize });
		}
		this.updatePosition();
		this.device.props.onDevicePixelRatioChange?.(this, { oldRatio });
	}
	updatePosition() {
		if (this.destroyed) return;
		const newRect = this.htmlCanvas?.getBoundingClientRect();
		if (newRect) {
			const position = [newRect.left, newRect.top];
			this._position ??= position;
			if (position[0] !== this._position[0] || position[1] !== this._position[1]) {
				const oldPosition = this._position;
				this._position = position;
				this.device.props.onPositionChange?.(this, { oldPosition });
			}
		}
	}
};
function getContainer(container) {
	if (typeof container === "string") {
		const element = document.getElementById(container);
		if (!element) throw new Error(`${container} is not an HTML element`);
		return element;
	}
	if (container) return container;
	return document.body;
}
function getCanvasFromDOM(canvasId) {
	const canvas = document.getElementById(canvasId);
	if (!CanvasSurface.isHTMLCanvas(canvas)) throw new Error("Object is not a canvas element");
	return canvas;
}
function createCanvasElement(props) {
	const { width, height } = props;
	const newCanvas = document.createElement("canvas");
	newCanvas.id = uid$1("lumagl-auto-created-canvas");
	newCanvas.width = width || 1;
	newCanvas.height = height || 1;
	newCanvas.style.width = Number.isFinite(width) ? `${width}px` : "100%";
	newCanvas.style.height = Number.isFinite(height) ? `${height}px` : "100%";
	if (!props?.visible) newCanvas.style.visibility = "hidden";
	const container = getContainer(props?.container || null);
	container.insertBefore(newCanvas, container.firstChild);
	return newCanvas;
}
function scalePixels(pixel, ratio, width, height, yInvert) {
	const point = pixel;
	const x = scaleX(point[0], ratio, width);
	let y = scaleY(point[1], ratio, height, yInvert);
	let temporary = scaleX(point[0] + 1, ratio, width);
	const xHigh = temporary === width - 1 ? temporary : temporary - 1;
	temporary = scaleY(point[1] + 1, ratio, height, yInvert);
	let yHigh;
	if (yInvert) {
		temporary = temporary === 0 ? temporary : temporary + 1;
		yHigh = y;
		y = temporary;
	} else yHigh = temporary === height - 1 ? temporary : temporary - 1;
	return {
		x,
		y,
		width: Math.max(xHigh - x + 1, 1),
		height: Math.max(yHigh - y + 1, 1)
	};
}
function scaleX(x, ratio, width) {
	return Math.min(Math.round(x * ratio), width - 1);
}
function scaleY(y, ratio, height, yInvert) {
	return yInvert ? Math.max(0, height - 1 - Math.round(y * ratio)) : Math.min(Math.round(y * ratio), height - 1);
}
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/canvas-context.js
/**
* Manages a renderable backend canvas. Supports both HTML or offscreen canvas
* and returns backend framebuffers sourced from the canvas itself.
*/
var CanvasContext = class extends CanvasSurface {
	static defaultProps = CanvasSurface.defaultProps;
};
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/presentation-context.js
/**
* Tracks a destination canvas for presentation.
* Backend implementations either borrow the default GPU-backed canvas (WebGL)
* or render directly into the destination canvas (WebGPU).
*/
var PresentationContext = class extends CanvasSurface {};
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/resources/texture-view.js
/** Immutable TextureView object */
var TextureView = class TextureView extends Resource {
	get [Symbol.toStringTag]() {
		return "TextureView";
	}
	/** Should not be constructed directly. Use `texture.createView(props)` */
	constructor(device, props) {
		super(device, props, TextureView.defaultProps);
	}
	static defaultProps = {
		...Resource.defaultProps,
		format: void 0,
		dimension: void 0,
		aspect: "all",
		baseMipLevel: 0,
		mipLevelCount: void 0,
		baseArrayLayer: 0,
		arrayLayerCount: void 0
	};
};
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter-utils/format-compiler-log.js
/** @returns annotated errors or warnings */
function formatCompilerLog(shaderLog, source, options) {
	let formattedLog = "";
	const lines = source.split(/\r?\n/);
	const log = shaderLog.slice().sort((a, b) => a.lineNum - b.lineNum);
	switch (options?.showSourceCode || "no") {
		case "all":
			let currentMessageIndex = 0;
			for (let lineNum = 1; lineNum <= lines.length; lineNum++) {
				const line = lines[lineNum - 1];
				const currentMessage = log[currentMessageIndex];
				if (line && currentMessage) formattedLog += getNumberedLine(line, lineNum, options);
				while (log.length > currentMessageIndex && currentMessage.lineNum === lineNum) {
					const message = log[currentMessageIndex++];
					if (message) formattedLog += formatCompilerMessage(message, lines, message.lineNum, {
						...options,
						inlineSource: false
					});
				}
			}
			while (log.length > currentMessageIndex) {
				const message = log[currentMessageIndex++];
				if (message) formattedLog += formatCompilerMessage(message, [], 0, {
					...options,
					inlineSource: false
				});
			}
			return formattedLog;
		case "issues":
		case "no":
			for (const message of shaderLog) formattedLog += formatCompilerMessage(message, lines, message.lineNum, { inlineSource: options?.showSourceCode !== "no" });
			return formattedLog;
	}
}
/** Format one message */
function formatCompilerMessage(message, lines, lineNum, options) {
	if (options?.inlineSource) return `
${getNumberedLines(lines, lineNum)}${message.linePos > 0 ? `${" ".repeat(message.linePos + 5)}^^^\n` : ""}${message.type.toUpperCase()}: ${message.message}

`;
	const color = message.type === "error" ? "red" : "orange";
	return options?.html ? `<div class='luma-compiler-log-${message.type}' style="color:${color};"><b> ${message.type.toUpperCase()}: ${message.message}</b></div>` : `${message.type.toUpperCase()}: ${message.message}`;
}
function getNumberedLines(lines, lineNum, options) {
	let numberedLines = "";
	for (let lineIndex = lineNum - 2; lineIndex <= lineNum; lineIndex++) {
		const sourceLine = lines[lineIndex - 1];
		if (sourceLine !== void 0) numberedLines += getNumberedLine(sourceLine, lineNum, options);
	}
	return numberedLines;
}
function getNumberedLine(line, lineNum, options) {
	const escapedLine = options?.html ? escapeHTML(line) : line;
	return `${padLeft(String(lineNum), 4)}: ${escapedLine}${options?.html ? "<br/>" : "\n"}`;
}
/**
* Pads a string with a number of spaces (space characters) to the left
* @param {String} string - string to pad
* @param {Number} digits - number of spaces to add
* @return {String} string - The padded string
*/
function padLeft(string, paddedLength) {
	let result = "";
	for (let i = string.length; i < paddedLength; ++i) result += " ";
	return result + string;
}
function escapeHTML(unsafe) {
	return unsafe.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll("\"", "&quot;").replaceAll("'", "&#039;");
}
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/resources/shader.js
/**
* Immutable Shader object
* In WebGPU the handle can be copied between threads
*/
var Shader = class Shader extends Resource {
	get [Symbol.toStringTag]() {
		return "Shader";
	}
	/** The stage of this shader */
	stage;
	/** The source code of this shader */
	source;
	/** The compilation status of the shader. 'pending' if compilation is asynchronous, and on production */
	compilationStatus = "pending";
	/** Create a new Shader instance */
	constructor(device, props) {
		props = {
			...props,
			debugShaders: props.debugShaders || device.props.debugShaders || "errors"
		};
		super(device, {
			id: getShaderIdFromProps(props),
			...props
		}, Shader.defaultProps);
		this.stage = this.props.stage;
		this.source = this.props.source;
	}
	/** Get compiler log synchronously (WebGL only) */
	getCompilationInfoSync() {
		return null;
	}
	/** Get translated shader source in host platform's native language (HLSL, GLSL, and even GLSL ES), if available */
	getTranslatedSource() {
		return null;
	}
	/** In browser logging of errors */
	async debugShader() {
		const trigger = this.props.debugShaders;
		switch (trigger) {
			case "never": return;
			case "errors":
				if (this.compilationStatus === "success") return;
				break;
			case "warnings":
			case "always": break;
		}
		const messages = await this.getCompilationInfo();
		if (trigger === "warnings" && messages?.length === 0) return;
		this._displayShaderLog(messages, this.id);
	}
	/**
	* In-browser UI logging of errors
	* TODO - this HTML formatting code should not be in Device, should be pluggable
	*/
	_displayShaderLog(messages, shaderId) {
		if (typeof document === "undefined" || !document?.createElement) return;
		const shaderName = shaderId;
		const shaderTitle = `${this.stage} shader "${shaderName}"`;
		const htmlLog = formatCompilerLog(messages, this.source, {
			showSourceCode: "all",
			html: true
		});
		const translatedSource = this.getTranslatedSource();
		const container = document.createElement("div");
		container.innerHTML = `\
<h1>Compilation error in ${shaderTitle}</h1>
<div style="display:flex;position:fixed;top:10px;right:20px;gap:2px;">
<button id="copy">Copy source</button><br/>
<button id="close">Close</button>
</div>
<code><pre>${htmlLog}</pre></code>`;
		if (translatedSource) container.innerHTML += `<br /><h1>Translated Source</h1><br /><br /><code><pre>${translatedSource}</pre></code>`;
		container.style.top = "0";
		container.style.left = "0";
		container.style.background = "white";
		container.style.position = "fixed";
		container.style.zIndex = "9999";
		container.style.maxWidth = "100vw";
		container.style.maxHeight = "100vh";
		container.style.overflowY = "auto";
		document.body.appendChild(container);
		container.querySelector(".luma-compiler-log-error")?.scrollIntoView();
		container.querySelector("button#close").onclick = () => {
			container.remove();
		};
		container.querySelector("button#copy").onclick = () => {
			navigator.clipboard.writeText(this.source);
		};
	}
	static defaultProps = {
		...Resource.defaultProps,
		language: "auto",
		stage: void 0,
		source: "",
		sourceMap: null,
		entryPoint: "main",
		debugShaders: void 0
	};
};
/** Deduce an id, from shader source, or supplied id, or shader type */
function getShaderIdFromProps(props) {
	return getShaderName(props.source) || props.id || uid$1(`unnamed ${props.stage}-shader`);
}
/** Extracts GLSLIFY style naming of shaders: `#define SHADER_NAME ...` */
function getShaderName(shader, defaultName = "unnamed") {
	return /#define[\s*]SHADER_NAME[\s*]([A-Za-z0-9_-]+)[\s*]/.exec(shader)?.[1] ?? defaultName;
}
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/resources/framebuffer.js
/**
* Create new textures with correct size for all attachments.
* @note resize() destroys existing textures (if size has changed).
*/
var Framebuffer = class Framebuffer extends Resource {
	get [Symbol.toStringTag]() {
		return "Framebuffer";
	}
	/** Width of all attachments in this framebuffer */
	width;
	/** Height of all attachments in this framebuffer */
	height;
	constructor(device, props = {}) {
		super(device, props, Framebuffer.defaultProps);
		this.width = this.props.width;
		this.height = this.props.height;
	}
	/**
	* Create a copy of this framebuffer with new attached textures, with same props but of the specified size.
	* @note Does not copy contents of the attached textures.
	*/
	clone(size) {
		const colorAttachments = this.colorAttachments.map((colorAttachment) => colorAttachment.texture.clone(size));
		const depthStencilAttachment = this.depthStencilAttachment && this.depthStencilAttachment.texture.clone(size);
		return this.device.createFramebuffer({
			...this.props,
			...size,
			colorAttachments,
			depthStencilAttachment
		});
	}
	resize(size) {
		let updateSize = !size;
		if (size) {
			const [width, height] = Array.isArray(size) ? size : [size.width, size.height];
			updateSize = updateSize || height !== this.height || width !== this.width;
			this.width = width;
			this.height = height;
		}
		if (updateSize) {
			log.log(2, `Resizing framebuffer ${this.id} to ${this.width}x${this.height}`)();
			this.resizeAttachments(this.width, this.height);
		}
	}
	/** Auto creates any textures */
	autoCreateAttachmentTextures() {
		if (this.props.colorAttachments.length === 0 && !this.props.depthStencilAttachment) throw new Error("Framebuffer has noattachments");
		this.colorAttachments = this.props.colorAttachments.map((attachment, index) => {
			if (typeof attachment === "string") {
				const texture = this.createColorTexture(attachment, index);
				this.attachResource(texture);
				return texture.view;
			}
			if (attachment instanceof Texture) return attachment.view;
			return attachment;
		});
		const attachment = this.props.depthStencilAttachment;
		if (attachment) if (typeof attachment === "string") {
			const texture = this.createDepthStencilTexture(attachment);
			this.attachResource(texture);
			this.depthStencilAttachment = texture.view;
		} else if (attachment instanceof Texture) this.depthStencilAttachment = attachment.view;
		else this.depthStencilAttachment = attachment;
	}
	/** Create a color texture */
	createColorTexture(format, index) {
		return this.device.createTexture({
			id: `${this.id}-color-attachment-${index}`,
			usage: Texture.RENDER_ATTACHMENT,
			format,
			width: this.width,
			height: this.height,
			sampler: {
				magFilter: "linear",
				minFilter: "linear"
			}
		});
	}
	/** Create depth stencil texture */
	createDepthStencilTexture(format) {
		return this.device.createTexture({
			id: `${this.id}-depth-stencil-attachment`,
			usage: Texture.RENDER_ATTACHMENT,
			format,
			width: this.width,
			height: this.height
		});
	}
	/**
	* Default implementation of resize
	* Creates new textures with correct size for all attachments.
	* and destroys existing textures if owned
	*/
	resizeAttachments(width, height) {
		this.colorAttachments.forEach((colorAttachment, i) => {
			const resizedTexture = colorAttachment.texture.clone({
				width,
				height
			});
			this.destroyAttachedResource(colorAttachment);
			this.colorAttachments[i] = resizedTexture.view;
			this.attachResource(resizedTexture.view);
		});
		if (this.depthStencilAttachment) {
			const resizedTexture = this.depthStencilAttachment.texture.clone({
				width,
				height
			});
			this.destroyAttachedResource(this.depthStencilAttachment);
			this.depthStencilAttachment = resizedTexture.view;
			this.attachResource(resizedTexture);
		}
		this.updateAttachments();
	}
	static defaultProps = {
		...Resource.defaultProps,
		width: 1,
		height: 1,
		colorAttachments: [],
		depthStencilAttachment: null
	};
};
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/resources/render-pipeline.js
/**
* A compiled and linked shader program
*/
var RenderPipeline = class RenderPipeline extends Resource {
	get [Symbol.toStringTag]() {
		return "RenderPipeline";
	}
	/** The merged layout */
	shaderLayout;
	/** Buffer map describing buffer interleaving etc */
	bufferLayout;
	/** The linking status of the pipeline. 'pending' if linking is asynchronous, and on production */
	linkStatus = "pending";
	/** The hash of the pipeline */
	hash = "";
	/** Optional shared backend implementation */
	sharedRenderPipeline = null;
	/** Whether shader or pipeline compilation/linking is still in progress */
	get isPending() {
		return this.linkStatus === "pending" || this.vs.compilationStatus === "pending" || this.fs?.compilationStatus === "pending";
	}
	/** Whether shader or pipeline compilation/linking has failed */
	get isErrored() {
		return this.linkStatus === "error" || this.vs.compilationStatus === "error" || this.fs?.compilationStatus === "error";
	}
	constructor(device, props) {
		super(device, props, RenderPipeline.defaultProps);
		this.shaderLayout = this.props.shaderLayout;
		this.bufferLayout = this.props.bufferLayout || [];
		this.sharedRenderPipeline = this.props._sharedRenderPipeline || null;
	}
	static defaultProps = {
		...Resource.defaultProps,
		vs: null,
		vertexEntryPoint: "vertexMain",
		vsConstants: {},
		fs: null,
		fragmentEntryPoint: "fragmentMain",
		fsConstants: {},
		shaderLayout: null,
		bufferLayout: [],
		topology: "triangle-list",
		colorAttachmentFormats: void 0,
		depthStencilAttachmentFormat: void 0,
		parameters: {},
		varyings: void 0,
		bufferMode: void 0,
		disableWarnings: false,
		_sharedRenderPipeline: void 0,
		bindings: void 0,
		bindGroups: void 0
	};
};
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/resources/shared-render-pipeline.js
/**
* Internal base class for backend-specific shared render-pipeline implementations.
* Backends may use this to share expensive linked/program state across multiple
* `RenderPipeline` wrappers.
*/
var SharedRenderPipeline = class extends Resource {
	get [Symbol.toStringTag]() {
		return "SharedRenderPipeline";
	}
	constructor(device, props) {
		super(device, props, {
			...Resource.defaultProps,
			handle: void 0,
			vs: void 0,
			fs: void 0,
			varyings: void 0,
			bufferMode: void 0
		});
	}
};
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter-utils/bind-groups.js
function getShaderLayoutBinding(shaderLayout, bindingName, options) {
	const bindingLayout = shaderLayout.bindings.find((binding) => binding.name === bindingName || `${binding.name.toLocaleLowerCase()}uniforms` === bindingName.toLocaleLowerCase());
	if (!bindingLayout && !options?.ignoreWarnings) log.warn(`Binding ${bindingName} not set: Not found in shader layout.`)();
	return bindingLayout || null;
}
function normalizeBindingsByGroup(shaderLayout, bindingsOrBindGroups) {
	if (!bindingsOrBindGroups) return {};
	if (areBindingsGrouped(bindingsOrBindGroups)) return Object.fromEntries(Object.entries(bindingsOrBindGroups).map(([group, bindings]) => [Number(group), { ...bindings }]));
	const bindGroups = {};
	for (const [bindingName, binding] of Object.entries(bindingsOrBindGroups)) {
		const group = getShaderLayoutBinding(shaderLayout, bindingName)?.group ?? 0;
		bindGroups[group] ||= {};
		bindGroups[group][bindingName] = binding;
	}
	return bindGroups;
}
function flattenBindingsByGroup(bindGroups) {
	const bindings = {};
	for (const groupBindings of Object.values(bindGroups)) Object.assign(bindings, groupBindings);
	return bindings;
}
function areBindingsGrouped(bindingsOrBindGroups) {
	const keys = Object.keys(bindingsOrBindGroups);
	return keys.length > 0 && keys.every((key) => /^\d+$/.test(key));
}
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/resources/render-pass.js
/**
* A RenderPass instance is a required parameter to all draw calls.
*
* It holds a combination of
* - render targets (specified via a framebuffer)
* - clear colors, read/write, discard information for the framebuffer attachments
* - a couple of mutable parameters ()
*/
var RenderPass = class RenderPass extends Resource {
	/** TODO - should be [0, 0, 0, 0], update once deck.gl tests run clean */
	static defaultClearColor = [
		0,
		0,
		0,
		1
	];
	/** Depth 1.0 represents the far plance */
	static defaultClearDepth = 1;
	/** Clears all stencil bits */
	static defaultClearStencil = 0;
	get [Symbol.toStringTag]() {
		return "RenderPass";
	}
	constructor(device, props) {
		props = RenderPass.normalizeProps(device, props);
		super(device, props, RenderPass.defaultProps);
	}
	static normalizeProps(device, props) {
		return props;
	}
	/** Default properties for RenderPass */
	static defaultProps = {
		...Resource.defaultProps,
		framebuffer: null,
		parameters: void 0,
		clearColor: RenderPass.defaultClearColor,
		clearColors: void 0,
		clearDepth: RenderPass.defaultClearDepth,
		clearStencil: RenderPass.defaultClearStencil,
		depthReadOnly: false,
		stencilReadOnly: false,
		discard: false,
		occlusionQuerySet: void 0,
		timestampQuerySet: void 0,
		beginTimestampIndex: void 0,
		endTimestampIndex: void 0
	};
};
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/resources/command-encoder.js
/**
* Records commands onto a single backend command encoder and can finish them into one command
* buffer. Resource helpers invoked through a CommandEncoder must record onto that encoder rather
* than allocating hidden encoders or submitting work eagerly.
*/
var CommandEncoder = class CommandEncoder extends Resource {
	get [Symbol.toStringTag]() {
		return "CommandEncoder";
	}
	_timeProfilingQuerySet = null;
	_timeProfilingSlotCount = 0;
	_gpuTimeMs;
	constructor(device, props) {
		super(device, props, CommandEncoder.defaultProps);
		this._timeProfilingQuerySet = props.timeProfilingQuerySet ?? null;
		this._timeProfilingSlotCount = 0;
		this._gpuTimeMs = void 0;
	}
	/**
	* Reads all resolved timestamp pairs on the current profiler query set and caches the sum
	* as milliseconds on this encoder.
	*/
	async resolveTimeProfilingQuerySet() {
		this._gpuTimeMs = void 0;
		if (!this._timeProfilingQuerySet) return;
		const pairCount = Math.floor(this._timeProfilingSlotCount / 2);
		if (pairCount <= 0) return;
		const queryCount = pairCount * 2;
		const results = await this._timeProfilingQuerySet.readResults({
			firstQuery: 0,
			queryCount
		});
		let totalDurationNanoseconds = 0n;
		for (let queryIndex = 0; queryIndex < queryCount; queryIndex += 2) totalDurationNanoseconds += results[queryIndex + 1] - results[queryIndex];
		this._gpuTimeMs = Number(totalDurationNanoseconds) / 1e6;
	}
	/** Returns the number of query slots consumed by automatic pass profiling on this encoder. */
	getTimeProfilingSlotCount() {
		return this._timeProfilingSlotCount;
	}
	getTimeProfilingQuerySet() {
		return this._timeProfilingQuerySet;
	}
	/** Internal helper for auto-assigning timestamp slots to render/compute passes on this encoder. */
	_applyTimeProfilingToPassProps(props) {
		const passProps = props || {};
		if (!this._supportsTimestampQueries() || !this._timeProfilingQuerySet) return passProps;
		if (passProps.timestampQuerySet !== void 0 || passProps.beginTimestampIndex !== void 0 || passProps.endTimestampIndex !== void 0) return passProps;
		const beginTimestampIndex = this._timeProfilingSlotCount;
		if (beginTimestampIndex + 1 >= this._timeProfilingQuerySet.props.count) return passProps;
		this._timeProfilingSlotCount += 2;
		return {
			...passProps,
			timestampQuerySet: this._timeProfilingQuerySet,
			beginTimestampIndex,
			endTimestampIndex: beginTimestampIndex + 1
		};
	}
	_supportsTimestampQueries() {
		return this.device.features.has("timestamp-query");
	}
	static defaultProps = {
		...Resource.defaultProps,
		measureExecutionTime: void 0,
		timeProfilingQuerySet: void 0
	};
};
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/resources/command-buffer.js
/**
* Represents the finished contents of exactly one CommandEncoder. Backends may store native
* command buffers or replayable command lists internally, but submission must preserve the same
* recorded command ordering.
*/
var CommandBuffer = class CommandBuffer extends Resource {
	get [Symbol.toStringTag]() {
		return "CommandBuffer";
	}
	constructor(device, props) {
		super(device, props, CommandBuffer.defaultProps);
	}
	static defaultProps = { ...Resource.defaultProps };
};
//#endregion
//#region node_modules/@luma.gl/core/dist/shadertypes/shader-types/shader-type-decoder.js
/** Split a uniform type string into type and components */
function getVariableShaderTypeInfo(format) {
	const decoded = UNIFORM_FORMATS[resolveVariableShaderTypeAlias(format)];
	if (!decoded) throw new Error(`Unsupported variable shader type: ${format}`);
	return decoded;
}
/** Decodes a vertex type, returning byte length and flags (integer, signed, normalized) */
function getAttributeShaderTypeInfo(attributeType) {
	const decoded = TYPE_INFO[resolveAttributeShaderTypeAlias(attributeType)];
	if (!decoded) throw new Error(`Unsupported attribute shader type: ${attributeType}`);
	const [primitiveType, components] = decoded;
	const integer = primitiveType === "i32" || primitiveType === "u32";
	const signed = primitiveType !== "u32";
	return {
		primitiveType,
		components,
		byteLength: PRIMITIVE_TYPE_SIZES[primitiveType] * components,
		integer,
		signed
	};
}
var ShaderTypeDecoder = class {
	getVariableShaderTypeInfo(format) {
		return getVariableShaderTypeInfo(format);
	}
	getAttributeShaderTypeInfo(attributeType) {
		return getAttributeShaderTypeInfo(attributeType);
	}
	makeShaderAttributeType(primitiveType, components) {
		return makeShaderAttributeType(primitiveType, components);
	}
	resolveAttributeShaderTypeAlias(alias) {
		return resolveAttributeShaderTypeAlias(alias);
	}
	resolveVariableShaderTypeAlias(alias) {
		return resolveVariableShaderTypeAlias(alias);
	}
};
function makeShaderAttributeType(primitiveType, components) {
	return components === 1 ? primitiveType : `vec${components}<${primitiveType}>`;
}
function resolveAttributeShaderTypeAlias(alias) {
	return WGSL_ATTRIBUTE_TYPE_ALIAS_MAP[alias] || alias;
}
function resolveVariableShaderTypeAlias(alias) {
	return WGSL_VARIABLE_TYPE_ALIAS_MAP[alias] || alias;
}
/** Decoder for luma.gl shader types */
var shaderTypeDecoder = new ShaderTypeDecoder();
var PRIMITIVE_TYPE_SIZES = {
	f32: 4,
	f16: 2,
	i32: 4,
	u32: 4
};
/** All valid shader attribute types. A table guarantees exhaustive list and fast execution */
var TYPE_INFO = {
	f32: ["f32", 1],
	"vec2<f32>": ["f32", 2],
	"vec3<f32>": ["f32", 3],
	"vec4<f32>": ["f32", 4],
	f16: ["f16", 1],
	"vec2<f16>": ["f16", 2],
	"vec3<f16>": ["f16", 3],
	"vec4<f16>": ["f16", 4],
	i32: ["i32", 1],
	"vec2<i32>": ["i32", 2],
	"vec3<i32>": ["i32", 3],
	"vec4<i32>": ["i32", 4],
	u32: ["u32", 1],
	"vec2<u32>": ["u32", 2],
	"vec3<u32>": ["u32", 3],
	"vec4<u32>": ["u32", 4]
};
/** @todo These tables are quite big, consider parsing type strings instead */
var UNIFORM_FORMATS = {
	f32: {
		type: "f32",
		components: 1
	},
	f16: {
		type: "f16",
		components: 1
	},
	i32: {
		type: "i32",
		components: 1
	},
	u32: {
		type: "u32",
		components: 1
	},
	"vec2<f32>": {
		type: "f32",
		components: 2
	},
	"vec3<f32>": {
		type: "f32",
		components: 3
	},
	"vec4<f32>": {
		type: "f32",
		components: 4
	},
	"vec2<f16>": {
		type: "f16",
		components: 2
	},
	"vec3<f16>": {
		type: "f16",
		components: 3
	},
	"vec4<f16>": {
		type: "f16",
		components: 4
	},
	"vec2<i32>": {
		type: "i32",
		components: 2
	},
	"vec3<i32>": {
		type: "i32",
		components: 3
	},
	"vec4<i32>": {
		type: "i32",
		components: 4
	},
	"vec2<u32>": {
		type: "u32",
		components: 2
	},
	"vec3<u32>": {
		type: "u32",
		components: 3
	},
	"vec4<u32>": {
		type: "u32",
		components: 4
	},
	"mat2x2<f32>": {
		type: "f32",
		components: 4
	},
	"mat2x3<f32>": {
		type: "f32",
		components: 6
	},
	"mat2x4<f32>": {
		type: "f32",
		components: 8
	},
	"mat3x2<f32>": {
		type: "f32",
		components: 6
	},
	"mat3x3<f32>": {
		type: "f32",
		components: 9
	},
	"mat3x4<f32>": {
		type: "f32",
		components: 12
	},
	"mat4x2<f32>": {
		type: "f32",
		components: 8
	},
	"mat4x3<f32>": {
		type: "f32",
		components: 12
	},
	"mat4x4<f32>": {
		type: "f32",
		components: 16
	},
	"mat2x2<f16>": {
		type: "f16",
		components: 4
	},
	"mat2x3<f16>": {
		type: "f16",
		components: 6
	},
	"mat2x4<f16>": {
		type: "f16",
		components: 8
	},
	"mat3x2<f16>": {
		type: "f16",
		components: 6
	},
	"mat3x3<f16>": {
		type: "f16",
		components: 9
	},
	"mat3x4<f16>": {
		type: "f16",
		components: 12
	},
	"mat4x2<f16>": {
		type: "f16",
		components: 8
	},
	"mat4x3<f16>": {
		type: "f16",
		components: 12
	},
	"mat4x4<f16>": {
		type: "f16",
		components: 16
	},
	"mat2x2<i32>": {
		type: "i32",
		components: 4
	},
	"mat2x3<i32>": {
		type: "i32",
		components: 6
	},
	"mat2x4<i32>": {
		type: "i32",
		components: 8
	},
	"mat3x2<i32>": {
		type: "i32",
		components: 6
	},
	"mat3x3<i32>": {
		type: "i32",
		components: 9
	},
	"mat3x4<i32>": {
		type: "i32",
		components: 12
	},
	"mat4x2<i32>": {
		type: "i32",
		components: 8
	},
	"mat4x3<i32>": {
		type: "i32",
		components: 12
	},
	"mat4x4<i32>": {
		type: "i32",
		components: 16
	},
	"mat2x2<u32>": {
		type: "u32",
		components: 4
	},
	"mat2x3<u32>": {
		type: "u32",
		components: 6
	},
	"mat2x4<u32>": {
		type: "u32",
		components: 8
	},
	"mat3x2<u32>": {
		type: "u32",
		components: 6
	},
	"mat3x3<u32>": {
		type: "u32",
		components: 9
	},
	"mat3x4<u32>": {
		type: "u32",
		components: 12
	},
	"mat4x2<u32>": {
		type: "u32",
		components: 8
	},
	"mat4x3<u32>": {
		type: "u32",
		components: 12
	},
	"mat4x4<u32>": {
		type: "u32",
		components: 16
	}
};
/**  Predeclared aliases @see https://www.w3.org/TR/WGSL/#vector-types */
var WGSL_ATTRIBUTE_TYPE_ALIAS_MAP = {
	vec2i: "vec2<i32>",
	vec3i: "vec3<i32>",
	vec4i: "vec4<i32>",
	vec2u: "vec2<u32>",
	vec3u: "vec3<u32>",
	vec4u: "vec4<u32>",
	vec2f: "vec2<f32>",
	vec3f: "vec3<f32>",
	vec4f: "vec4<f32>",
	vec2h: "vec2<f16>",
	vec3h: "vec3<f16>",
	vec4h: "vec4<f16>"
};
/** @todo These tables are quite big, consider parsing alias strings instead */
var WGSL_VARIABLE_TYPE_ALIAS_MAP = {
	vec2i: "vec2<i32>",
	vec3i: "vec3<i32>",
	vec4i: "vec4<i32>",
	vec2u: "vec2<u32>",
	vec3u: "vec3<u32>",
	vec4u: "vec4<u32>",
	vec2f: "vec2<f32>",
	vec3f: "vec3<f32>",
	vec4f: "vec4<f32>",
	vec2h: "vec2<f16>",
	vec3h: "vec3<f16>",
	vec4h: "vec4<f16>",
	mat2x2f: "mat2x2<f32>",
	mat2x3f: "mat2x3<f32>",
	mat2x4f: "mat2x4<f32>",
	mat3x2f: "mat3x2<f32>",
	mat3x3f: "mat3x3<f32>",
	mat3x4f: "mat3x4<f32>",
	mat4x2f: "mat4x2<f32>",
	mat4x3f: "mat4x3<f32>",
	mat4x4f: "mat4x4<f32>",
	mat2x2i: "mat2x2<i32>",
	mat2x3i: "mat2x3<i32>",
	mat2x4i: "mat2x4<i32>",
	mat3x2i: "mat3x2<i32>",
	mat3x3i: "mat3x3<i32>",
	mat3x4i: "mat3x4<i32>",
	mat4x2i: "mat4x2<i32>",
	mat4x3i: "mat4x3<i32>",
	mat4x4i: "mat4x4<i32>",
	mat2x2u: "mat2x2<u32>",
	mat2x3u: "mat2x3<u32>",
	mat2x4u: "mat2x4<u32>",
	mat3x2u: "mat3x2<u32>",
	mat3x3u: "mat3x3<u32>",
	mat3x4u: "mat3x4<u32>",
	mat4x2u: "mat4x2<u32>",
	mat4x3u: "mat4x3<u32>",
	mat4x4u: "mat4x4<u32>",
	mat2x2h: "mat2x2<f16>",
	mat2x3h: "mat2x3<f16>",
	mat2x4h: "mat2x4<f16>",
	mat3x2h: "mat3x2<f16>",
	mat3x3h: "mat3x3<f16>",
	mat3x4h: "mat3x4<f16>",
	mat4x2h: "mat4x2<f16>",
	mat4x3h: "mat4x3<f16>",
	mat4x4h: "mat4x4<f16>"
};
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter-utils/get-attribute-from-layouts.js
/**
* Map from "attribute names" to "resolved attribute infos"
* containing information about both buffer layouts and shader attribute declarations
*/
function getAttributeInfosFromLayouts(shaderLayout, bufferLayout) {
	const attributeInfos = {};
	for (const attribute of shaderLayout.attributes) {
		const attributeInfo = getAttributeInfoFromLayouts(shaderLayout, bufferLayout, attribute.name);
		if (attributeInfo) attributeInfos[attribute.name] = attributeInfo;
	}
	return attributeInfos;
}
/**
* Array indexed by "location" holding "resolved attribute infos"
*/
function getAttributeInfosByLocation(shaderLayout, bufferLayout, maxVertexAttributes = 16) {
	const attributeInfos = getAttributeInfosFromLayouts(shaderLayout, bufferLayout);
	const locationInfos = new Array(maxVertexAttributes).fill(null);
	for (const attributeInfo of Object.values(attributeInfos)) locationInfos[attributeInfo.location] = attributeInfo;
	return locationInfos;
}
/**
* Get the combined information from a shader layout and a buffer layout for a specific attribute
*/
function getAttributeInfoFromLayouts(shaderLayout, bufferLayout, name) {
	const shaderDeclaration = getAttributeFromShaderLayout(shaderLayout, name);
	const bufferMapping = getAttributeFromBufferLayout(bufferLayout, name);
	if (!shaderDeclaration) return null;
	const attributeTypeInfo = shaderTypeDecoder.getAttributeShaderTypeInfo(shaderDeclaration.type);
	const defaultVertexFormat = vertexFormatDecoder.getCompatibleVertexFormat(attributeTypeInfo);
	const vertexFormat = bufferMapping?.vertexFormat || defaultVertexFormat;
	const vertexFormatInfo = vertexFormatDecoder.getVertexFormatInfo(vertexFormat);
	return {
		attributeName: bufferMapping?.attributeName || shaderDeclaration.name,
		bufferName: bufferMapping?.bufferName || shaderDeclaration.name,
		location: shaderDeclaration.location,
		shaderType: shaderDeclaration.type,
		primitiveType: attributeTypeInfo.primitiveType,
		shaderComponents: attributeTypeInfo.components,
		vertexFormat,
		bufferDataType: vertexFormatInfo.type,
		bufferComponents: vertexFormatInfo.components,
		normalized: vertexFormatInfo.normalized,
		integer: attributeTypeInfo.integer,
		stepMode: bufferMapping?.stepMode || shaderDeclaration.stepMode || "vertex",
		byteOffset: bufferMapping?.byteOffset || 0,
		byteStride: bufferMapping?.byteStride || 0
	};
}
function getAttributeFromShaderLayout(shaderLayout, name) {
	const attribute = shaderLayout.attributes.find((attr) => attr.name === name);
	if (!attribute) log.warn(`shader layout attribute "${name}" not present in shader`);
	return attribute || null;
}
function getAttributeFromBufferLayout(bufferLayouts, name) {
	checkBufferLayouts(bufferLayouts);
	let bufferLayoutInfo = getAttributeFromShortHand(bufferLayouts, name);
	if (bufferLayoutInfo) return bufferLayoutInfo;
	bufferLayoutInfo = getAttributeFromAttributesList(bufferLayouts, name);
	if (bufferLayoutInfo) return bufferLayoutInfo;
	log.warn(`layout for attribute "${name}" not present in buffer layout`);
	return null;
}
/** Check that bufferLayouts are valid (each either has format or attribute) */
function checkBufferLayouts(bufferLayouts) {
	for (const bufferLayout of bufferLayouts) if (bufferLayout.attributes && bufferLayout.format || !bufferLayout.attributes && !bufferLayout.format) log.warn(`BufferLayout ${name} must have either 'attributes' or 'format' field`);
}
/** Get attribute from format shorthand if specified */
function getAttributeFromShortHand(bufferLayouts, name) {
	for (const bufferLayout of bufferLayouts) if (bufferLayout.format && bufferLayout.name === name) return {
		attributeName: bufferLayout.name,
		bufferName: name,
		stepMode: bufferLayout.stepMode,
		vertexFormat: bufferLayout.format,
		byteOffset: 0,
		byteStride: bufferLayout.byteStride || 0
	};
	return null;
}
/**
* Search attribute mappings (e.g. interleaved attributes) for buffer mapping.
* Not the name of the buffer might be the same as one of the interleaved attributes.
*/
function getAttributeFromAttributesList(bufferLayouts, name) {
	for (const bufferLayout of bufferLayouts) {
		let byteStride = bufferLayout.byteStride;
		if (typeof bufferLayout.byteStride !== "number") for (const attributeMapping of bufferLayout.attributes || []) {
			const info = vertexFormatDecoder.getVertexFormatInfo(attributeMapping.format);
			byteStride += info.byteLength;
		}
		const attributeMapping = bufferLayout.attributes?.find((mapping) => mapping.attribute === name);
		if (attributeMapping) return {
			attributeName: attributeMapping.attribute,
			bufferName: bufferLayout.name,
			stepMode: bufferLayout.stepMode,
			vertexFormat: attributeMapping.format,
			byteOffset: attributeMapping.byteOffset,
			byteStride
		};
	}
	return null;
}
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/resources/vertex-array.js
/**
* Stores attribute bindings.
* Makes it easy to share a render pipeline and use separate vertex arrays.
* @note On WebGL, VertexArray allows non-constant bindings to be performed in advance
* reducing the number of WebGL calls per draw call.
* @note On WebGPU this is just a convenience class that collects the bindings.
*/
var VertexArray = class VertexArray extends Resource {
	static defaultProps = {
		...Resource.defaultProps,
		shaderLayout: void 0,
		bufferLayout: []
	};
	get [Symbol.toStringTag]() {
		return "VertexArray";
	}
	/** Max number of vertex attributes */
	maxVertexAttributes;
	/** Attribute infos indexed by location - TODO only needed by webgl module? */
	attributeInfos;
	/** Index buffer */
	indexBuffer = null;
	/** Attributes indexed by buffer slot */
	attributes;
	constructor(device, props) {
		super(device, props, VertexArray.defaultProps);
		this.maxVertexAttributes = device.limits.maxVertexAttributes;
		this.attributes = new Array(this.maxVertexAttributes).fill(null);
		this.attributeInfos = getAttributeInfosByLocation(props.shaderLayout, props.bufferLayout, this.maxVertexAttributes);
	}
	/** @deprecated Set constant attributes (WebGL only) */
	setConstantWebGL(location, value) {
		this.device.reportError(/* @__PURE__ */ new Error("constant attributes not supported"), this)();
	}
};
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/resources/transform-feedback.js
/** Holds a set of output buffers for pipeline (WebGL only) */
var TransformFeedback = class TransformFeedback extends Resource {
	static defaultProps = {
		...Resource.defaultProps,
		layout: void 0,
		buffers: {}
	};
	get [Symbol.toStringTag]() {
		return "TransformFeedback";
	}
	constructor(device, props) {
		super(device, props, TransformFeedback.defaultProps);
	}
};
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/resources/query-set.js
/** Immutable QuerySet object */
var QuerySet = class QuerySet extends Resource {
	get [Symbol.toStringTag]() {
		return "QuerySet";
	}
	constructor(device, props) {
		super(device, props, QuerySet.defaultProps);
	}
	static defaultProps = {
		...Resource.defaultProps,
		type: void 0,
		count: void 0
	};
};
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/resources/fence.js
/** Synchronization primitive that resolves when GPU work is completed */
var Fence = class Fence extends Resource {
	static defaultProps = { ...Resource.defaultProps };
	get [Symbol.toStringTag]() {
		return "Fence";
	}
	constructor(device, props = {}) {
		super(device, props, Fence.defaultProps);
	}
};
//#endregion
//#region node_modules/@luma.gl/core/dist/shadertypes/data-types/decode-data-types.js
/** Align offset to 1, 2 or 4 elements (4, 8 or 16 bytes) */
function alignTo(size, count) {
	switch (count) {
		case 1: return size;
		case 2: return size + size % 2;
		default: return size + (4 - size % 4) % 4;
	}
}
/** Returns the TypedArray that corresponds to a shader data type */
function getTypedArrayConstructor(type) {
	const [, , , , Constructor] = NORMALIZED_TYPE_MAP[type];
	return Constructor;
}
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
//#region node_modules/@luma.gl/core/dist/utils/array-utils-flat.js
var arrayBuffer;
function getScratchArrayBuffer(byteLength) {
	if (!arrayBuffer || arrayBuffer.byteLength < byteLength) arrayBuffer = new ArrayBuffer(byteLength);
	return arrayBuffer;
}
function getScratchArray(Type, length) {
	return new Type(getScratchArrayBuffer(Type.BYTES_PER_ELEMENT * length), 0, length);
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/context/parameters/webgl-parameter-tables.js
var GL_PARAMETER_DEFAULTS = {
	[3042]: false,
	[32773]: new Float32Array([
		0,
		0,
		0,
		0
	]),
	[32777]: 32774,
	[34877]: 32774,
	[32969]: 1,
	[32968]: 0,
	[32971]: 1,
	[32970]: 0,
	[3106]: new Float32Array([
		0,
		0,
		0,
		0
	]),
	[3107]: [
		true,
		true,
		true,
		true
	],
	[2884]: false,
	[2885]: 1029,
	[2929]: false,
	[2931]: 1,
	[2932]: 513,
	[2928]: new Float32Array([0, 1]),
	[2930]: true,
	[3024]: true,
	[35725]: null,
	[36006]: null,
	[36007]: null,
	[34229]: null,
	[34964]: null,
	[2886]: 2305,
	[33170]: 4352,
	[2849]: 1,
	[32823]: false,
	[32824]: 0,
	[10752]: 0,
	[32926]: false,
	[32928]: false,
	[32938]: 1,
	[32939]: false,
	[3089]: false,
	[3088]: new Int32Array([
		0,
		0,
		1024,
		1024
	]),
	[2960]: false,
	[2961]: 0,
	[2968]: 4294967295,
	[36005]: 4294967295,
	[2962]: 519,
	[2967]: 0,
	[2963]: 4294967295,
	[34816]: 519,
	[36003]: 0,
	[36004]: 4294967295,
	[2964]: 7680,
	[2965]: 7680,
	[2966]: 7680,
	[34817]: 7680,
	[34818]: 7680,
	[34819]: 7680,
	[2978]: [
		0,
		0,
		1024,
		1024
	],
	[36389]: null,
	[36662]: null,
	[36663]: null,
	[35053]: null,
	[35055]: null,
	[35723]: 4352,
	[36010]: null,
	[35977]: false,
	[3333]: 4,
	[3317]: 4,
	[37440]: false,
	[37441]: false,
	[37443]: 37444,
	[3330]: 0,
	[3332]: 0,
	[3331]: 0,
	[3314]: 0,
	[32878]: 0,
	[3316]: 0,
	[3315]: 0,
	[32877]: 0
};
var enable = (gl, value, key) => value ? gl.enable(key) : gl.disable(key);
var hint = (gl, value, key) => gl.hint(key, value);
var pixelStorei = (gl, value, key) => gl.pixelStorei(key, value);
var bindFramebuffer = (gl, value, key) => {
	const target = key === 36006 ? 36009 : 36008;
	return gl.bindFramebuffer(target, value);
};
var bindBuffer = (gl, value, key) => {
	const glTarget = {
		[34964]: 34962,
		[36662]: 36662,
		[36663]: 36663,
		[35053]: 35051,
		[35055]: 35052
	}[key];
	gl.bindBuffer(glTarget, value);
};
function isArray$1(array) {
	return Array.isArray(array) || ArrayBuffer.isView(array) && !(array instanceof DataView);
}
var GL_PARAMETER_SETTERS = {
	[3042]: enable,
	[32773]: (gl, value) => gl.blendColor(...value),
	[32777]: "blendEquation",
	[34877]: "blendEquation",
	[32969]: "blendFunc",
	[32968]: "blendFunc",
	[32971]: "blendFunc",
	[32970]: "blendFunc",
	[3106]: (gl, value) => gl.clearColor(...value),
	[3107]: (gl, value) => gl.colorMask(...value),
	[2884]: enable,
	[2885]: (gl, value) => gl.cullFace(value),
	[2929]: enable,
	[2931]: (gl, value) => gl.clearDepth(value),
	[2932]: (gl, value) => gl.depthFunc(value),
	[2928]: (gl, value) => gl.depthRange(...value),
	[2930]: (gl, value) => gl.depthMask(value),
	[3024]: enable,
	[35723]: hint,
	[35725]: (gl, value) => gl.useProgram(value),
	[36007]: (gl, value) => gl.bindRenderbuffer(36161, value),
	[36389]: (gl, value) => gl.bindTransformFeedback?.(36386, value),
	[34229]: (gl, value) => gl.bindVertexArray(value),
	[36006]: bindFramebuffer,
	[36010]: bindFramebuffer,
	[34964]: bindBuffer,
	[36662]: bindBuffer,
	[36663]: bindBuffer,
	[35053]: bindBuffer,
	[35055]: bindBuffer,
	[2886]: (gl, value) => gl.frontFace(value),
	[33170]: hint,
	[2849]: (gl, value) => gl.lineWidth(value),
	[32823]: enable,
	[32824]: "polygonOffset",
	[10752]: "polygonOffset",
	[35977]: enable,
	[32926]: enable,
	[32928]: enable,
	[32938]: "sampleCoverage",
	[32939]: "sampleCoverage",
	[3089]: enable,
	[3088]: (gl, value) => gl.scissor(...value),
	[2960]: enable,
	[2961]: (gl, value) => gl.clearStencil(value),
	[2968]: (gl, value) => gl.stencilMaskSeparate(1028, value),
	[36005]: (gl, value) => gl.stencilMaskSeparate(1029, value),
	[2962]: "stencilFuncFront",
	[2967]: "stencilFuncFront",
	[2963]: "stencilFuncFront",
	[34816]: "stencilFuncBack",
	[36003]: "stencilFuncBack",
	[36004]: "stencilFuncBack",
	[2964]: "stencilOpFront",
	[2965]: "stencilOpFront",
	[2966]: "stencilOpFront",
	[34817]: "stencilOpBack",
	[34818]: "stencilOpBack",
	[34819]: "stencilOpBack",
	[2978]: (gl, value) => gl.viewport(...value),
	[34383]: enable,
	[10754]: enable,
	[12288]: enable,
	[12289]: enable,
	[12290]: enable,
	[12291]: enable,
	[12292]: enable,
	[12293]: enable,
	[12294]: enable,
	[12295]: enable,
	[3333]: pixelStorei,
	[3317]: pixelStorei,
	[37440]: pixelStorei,
	[37441]: pixelStorei,
	[37443]: pixelStorei,
	[3330]: pixelStorei,
	[3332]: pixelStorei,
	[3331]: pixelStorei,
	[3314]: pixelStorei,
	[32878]: pixelStorei,
	[3316]: pixelStorei,
	[3315]: pixelStorei,
	[32877]: pixelStorei,
	framebuffer: (gl, framebuffer) => {
		const handle = framebuffer && "handle" in framebuffer ? framebuffer.handle : framebuffer;
		return gl.bindFramebuffer(36160, handle);
	},
	blend: (gl, value) => value ? gl.enable(3042) : gl.disable(3042),
	blendColor: (gl, value) => gl.blendColor(...value),
	blendEquation: (gl, args) => {
		const separateModes = typeof args === "number" ? [args, args] : args;
		gl.blendEquationSeparate(...separateModes);
	},
	blendFunc: (gl, args) => {
		const separateFuncs = args?.length === 2 ? [...args, ...args] : args;
		gl.blendFuncSeparate(...separateFuncs);
	},
	clearColor: (gl, value) => gl.clearColor(...value),
	clearDepth: (gl, value) => gl.clearDepth(value),
	clearStencil: (gl, value) => gl.clearStencil(value),
	colorMask: (gl, value) => gl.colorMask(...value),
	cull: (gl, value) => value ? gl.enable(2884) : gl.disable(2884),
	cullFace: (gl, value) => gl.cullFace(value),
	depthTest: (gl, value) => value ? gl.enable(2929) : gl.disable(2929),
	depthFunc: (gl, value) => gl.depthFunc(value),
	depthMask: (gl, value) => gl.depthMask(value),
	depthRange: (gl, value) => gl.depthRange(...value),
	dither: (gl, value) => value ? gl.enable(3024) : gl.disable(3024),
	derivativeHint: (gl, value) => {
		gl.hint(35723, value);
	},
	frontFace: (gl, value) => gl.frontFace(value),
	mipmapHint: (gl, value) => gl.hint(33170, value),
	lineWidth: (gl, value) => gl.lineWidth(value),
	polygonOffsetFill: (gl, value) => value ? gl.enable(32823) : gl.disable(32823),
	polygonOffset: (gl, value) => gl.polygonOffset(...value),
	sampleCoverage: (gl, value) => gl.sampleCoverage(value[0], value[1] || false),
	scissorTest: (gl, value) => value ? gl.enable(3089) : gl.disable(3089),
	scissor: (gl, value) => gl.scissor(...value),
	stencilTest: (gl, value) => value ? gl.enable(2960) : gl.disable(2960),
	stencilMask: (gl, value) => {
		value = isArray$1(value) ? value : [value, value];
		const [mask, backMask] = value;
		gl.stencilMaskSeparate(1028, mask);
		gl.stencilMaskSeparate(1029, backMask);
	},
	stencilFunc: (gl, args) => {
		args = isArray$1(args) && args.length === 3 ? [...args, ...args] : args;
		const [func, ref, mask, backFunc, backRef, backMask] = args;
		gl.stencilFuncSeparate(1028, func, ref, mask);
		gl.stencilFuncSeparate(1029, backFunc, backRef, backMask);
	},
	stencilOp: (gl, args) => {
		args = isArray$1(args) && args.length === 3 ? [...args, ...args] : args;
		const [sfail, dpfail, dppass, backSfail, backDpfail, backDppass] = args;
		gl.stencilOpSeparate(1028, sfail, dpfail, dppass);
		gl.stencilOpSeparate(1029, backSfail, backDpfail, backDppass);
	},
	viewport: (gl, value) => gl.viewport(...value)
};
function getValue(glEnum, values, cache) {
	return values[glEnum] !== void 0 ? values[glEnum] : cache[glEnum];
}
var GL_COMPOSITE_PARAMETER_SETTERS = {
	blendEquation: (gl, values, cache) => gl.blendEquationSeparate(getValue(32777, values, cache), getValue(34877, values, cache)),
	blendFunc: (gl, values, cache) => gl.blendFuncSeparate(getValue(32969, values, cache), getValue(32968, values, cache), getValue(32971, values, cache), getValue(32970, values, cache)),
	polygonOffset: (gl, values, cache) => gl.polygonOffset(getValue(32824, values, cache), getValue(10752, values, cache)),
	sampleCoverage: (gl, values, cache) => gl.sampleCoverage(getValue(32938, values, cache), getValue(32939, values, cache)),
	stencilFuncFront: (gl, values, cache) => gl.stencilFuncSeparate(1028, getValue(2962, values, cache), getValue(2967, values, cache), getValue(2963, values, cache)),
	stencilFuncBack: (gl, values, cache) => gl.stencilFuncSeparate(1029, getValue(34816, values, cache), getValue(36003, values, cache), getValue(36004, values, cache)),
	stencilOpFront: (gl, values, cache) => gl.stencilOpSeparate(1028, getValue(2964, values, cache), getValue(2965, values, cache), getValue(2966, values, cache)),
	stencilOpBack: (gl, values, cache) => gl.stencilOpSeparate(1029, getValue(34817, values, cache), getValue(34818, values, cache), getValue(34819, values, cache))
};
var GL_HOOKED_SETTERS = {
	enable: (update, capability) => update({ [capability]: true }),
	disable: (update, capability) => update({ [capability]: false }),
	pixelStorei: (update, pname, value) => update({ [pname]: value }),
	hint: (update, pname, value) => update({ [pname]: value }),
	useProgram: (update, value) => update({ [35725]: value }),
	bindRenderbuffer: (update, target, value) => update({ [36007]: value }),
	bindTransformFeedback: (update, target, value) => update({ [36389]: value }),
	bindVertexArray: (update, value) => update({ [34229]: value }),
	bindFramebuffer: (update, target, framebuffer) => {
		switch (target) {
			case 36160: return update({
				[36006]: framebuffer,
				[36010]: framebuffer
			});
			case 36009: return update({ [36006]: framebuffer });
			case 36008: return update({ [36010]: framebuffer });
			default: return null;
		}
	},
	bindBuffer: (update, target, buffer) => {
		const pname = {
			[34962]: [34964],
			[36662]: [36662],
			[36663]: [36663],
			[35051]: [35053],
			[35052]: [35055]
		}[target];
		if (pname) return update({ [pname]: buffer });
		return { valueChanged: true };
	},
	blendColor: (update, r, g, b, a) => update({ [32773]: new Float32Array([
		r,
		g,
		b,
		a
	]) }),
	blendEquation: (update, mode) => update({
		[32777]: mode,
		[34877]: mode
	}),
	blendEquationSeparate: (update, modeRGB, modeAlpha) => update({
		[32777]: modeRGB,
		[34877]: modeAlpha
	}),
	blendFunc: (update, src, dst) => update({
		[32969]: src,
		[32968]: dst,
		[32971]: src,
		[32970]: dst
	}),
	blendFuncSeparate: (update, srcRGB, dstRGB, srcAlpha, dstAlpha) => update({
		[32969]: srcRGB,
		[32968]: dstRGB,
		[32971]: srcAlpha,
		[32970]: dstAlpha
	}),
	clearColor: (update, r, g, b, a) => update({ [3106]: new Float32Array([
		r,
		g,
		b,
		a
	]) }),
	clearDepth: (update, depth) => update({ [2931]: depth }),
	clearStencil: (update, s) => update({ [2961]: s }),
	colorMask: (update, r, g, b, a) => update({ [3107]: [
		r,
		g,
		b,
		a
	] }),
	cullFace: (update, mode) => update({ [2885]: mode }),
	depthFunc: (update, func) => update({ [2932]: func }),
	depthRange: (update, zNear, zFar) => update({ [2928]: new Float32Array([zNear, zFar]) }),
	depthMask: (update, mask) => update({ [2930]: mask }),
	frontFace: (update, face) => update({ [2886]: face }),
	lineWidth: (update, width) => update({ [2849]: width }),
	polygonOffset: (update, factor, units) => update({
		[32824]: factor,
		[10752]: units
	}),
	sampleCoverage: (update, value, invert) => update({
		[32938]: value,
		[32939]: invert
	}),
	scissor: (update, x, y, width, height) => update({ [3088]: new Int32Array([
		x,
		y,
		width,
		height
	]) }),
	stencilMask: (update, mask) => update({
		[2968]: mask,
		[36005]: mask
	}),
	stencilMaskSeparate: (update, face, mask) => update({ [face === 1028 ? 2968 : 36005]: mask }),
	stencilFunc: (update, func, ref, mask) => update({
		[2962]: func,
		[2967]: ref,
		[2963]: mask,
		[34816]: func,
		[36003]: ref,
		[36004]: mask
	}),
	stencilFuncSeparate: (update, face, func, ref, mask) => update({
		[face === 1028 ? 2962 : 34816]: func,
		[face === 1028 ? 2967 : 36003]: ref,
		[face === 1028 ? 2963 : 36004]: mask
	}),
	stencilOp: (update, fail, zfail, zpass) => update({
		[2964]: fail,
		[2965]: zfail,
		[2966]: zpass,
		[34817]: fail,
		[34818]: zfail,
		[34819]: zpass
	}),
	stencilOpSeparate: (update, face, fail, zfail, zpass) => update({
		[face === 1028 ? 2964 : 34817]: fail,
		[face === 1028 ? 2965 : 34818]: zfail,
		[face === 1028 ? 2966 : 34819]: zpass
	}),
	viewport: (update, x, y, width, height) => update({ [2978]: [
		x,
		y,
		width,
		height
	] })
};
var isEnabled = (gl, key) => gl.isEnabled(key);
var GL_PARAMETER_GETTERS = {
	[3042]: isEnabled,
	[2884]: isEnabled,
	[2929]: isEnabled,
	[3024]: isEnabled,
	[32823]: isEnabled,
	[32926]: isEnabled,
	[32928]: isEnabled,
	[3089]: isEnabled,
	[2960]: isEnabled,
	[35977]: isEnabled
};
var NON_CACHE_PARAMETERS = new Set([
	34016,
	36388,
	36387,
	35983,
	35368,
	34965,
	35739,
	35738,
	3074,
	34853,
	34854,
	34855,
	34856,
	34857,
	34858,
	34859,
	34860,
	34861,
	34862,
	34863,
	34864,
	34865,
	34866,
	34867,
	34868,
	35097,
	32873,
	35869,
	32874,
	34068
]);
//#endregion
//#region node_modules/@luma.gl/webgl/dist/context/parameters/unified-parameter-api.js
/**
* Sets any GL parameter regardless of function (gl.blendMode, ...)
*
* @note requires a `cache` object to be set on the context (lumaState.cache)
* This object is used to fill in any missing values for composite setter functions
*/
function setGLParameters(gl, parameters) {
	if (isObjectEmpty$2(parameters)) return;
	const compositeSetters = {};
	for (const key in parameters) {
		const glConstant = Number(key);
		const setter = GL_PARAMETER_SETTERS[key];
		if (setter) if (typeof setter === "string") compositeSetters[setter] = true;
		else setter(gl, parameters[key], glConstant);
	}
	const cache = gl.lumaState?.cache;
	if (cache) for (const key in compositeSetters) {
		const compositeSetter = GL_COMPOSITE_PARAMETER_SETTERS[key];
		compositeSetter(gl, parameters, cache);
	}
}
/**
* Reads the entire WebGL state from a context

// default to querying all parameters

* @returns - a newly created map, with values keyed by GL parameters
*
* @note Copies the state from a context (gl.getParameter should not be overriden)
* Reads the entire WebGL state from a context
*
* @note This can generates a huge amount of synchronous driver roundtrips and should be
* considered a very slow operation, to be used only if/when a context already manipulated
* by external code needs to be synchronized for the first time
*/
function getGLParameters(gl, parameters = GL_PARAMETER_DEFAULTS) {
	if (typeof parameters === "number") {
		const key = parameters;
		const getter = GL_PARAMETER_GETTERS[key];
		return getter ? getter(gl, key) : gl.getParameter(key);
	}
	const parameterKeys = Array.isArray(parameters) ? parameters : Object.keys(parameters);
	const state = {};
	for (const key of parameterKeys) {
		const getter = GL_PARAMETER_GETTERS[key];
		state[key] = getter ? getter(gl, Number(key)) : gl.getParameter(Number(key));
	}
	return state;
}
/**
* Reset all parameters to a (almost) pure context state
* @note viewport and scissor will be set to the values in GL_PARAMETER_DEFAULTS,
* NOT the canvas size dimensions, so they will have to be properly set after
* calling this function.
*/
function resetGLParameters(gl) {
	setGLParameters(gl, GL_PARAMETER_DEFAULTS);
}
function isObjectEmpty$2(object) {
	for (const key in object) return false;
	return true;
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/context/state-tracker/deep-array-equal.js
/** deeply compare two arrays */
function deepArrayEqual(x, y) {
	if (x === y) return true;
	if (isArray(x) && isArray(y) && x.length === y.length) {
		for (let i = 0; i < x.length; ++i) if (x[i] !== y[i]) return false;
		return true;
	}
	return false;
}
function isArray(x) {
	return Array.isArray(x) || ArrayBuffer.isView(x);
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/context/state-tracker/webgl-state-tracker.js
/**
* Support for listening to context state changes and intercepting state queries
* NOTE: this system does not handle buffer bindings
*/
var WebGLStateTracker = class {
	static get(gl) {
		return gl.lumaState;
	}
	gl;
	program = null;
	stateStack = [];
	enable = true;
	cache = null;
	log;
	initialized = false;
	constructor(gl, props) {
		this.gl = gl;
		this.log = props?.log || (() => {});
		this._updateCache = this._updateCache.bind(this);
		Object.seal(this);
	}
	push(values = {}) {
		this.stateStack.push({});
	}
	pop() {
		const oldValues = this.stateStack[this.stateStack.length - 1];
		setGLParameters(this.gl, oldValues);
		this.stateStack.pop();
	}
	/**
	* Initialize WebGL state caching on a context
	* can be called multiple times to enable/disable
	*
	* @note After calling this function, context state will be cached
	* .push() and .pop() will be available for saving,
	* temporarily modifying, and then restoring state.
	*/
	trackState(gl, options) {
		this.cache = options?.copyState ? getGLParameters(gl) : Object.assign({}, GL_PARAMETER_DEFAULTS);
		if (this.initialized) throw new Error("WebGLStateTracker");
		this.initialized = true;
		this.gl.lumaState = this;
		installProgramSpy(gl);
		for (const key in GL_HOOKED_SETTERS) {
			const setter = GL_HOOKED_SETTERS[key];
			installSetterSpy(gl, key, setter);
		}
		installGetterOverride(gl, "getParameter");
		installGetterOverride(gl, "isEnabled");
	}
	/**
	// interceptor for context set functions - update our cache and our stack
	// values (Object) - the key values for this setter
	* @param values
	* @returns
	*/
	_updateCache(values) {
		let valueChanged = false;
		let oldValue;
		const oldValues = this.stateStack.length > 0 ? this.stateStack[this.stateStack.length - 1] : null;
		for (const key in values) {
			const value = values[key];
			const cached = this.cache[key];
			if (!deepArrayEqual(value, cached)) {
				valueChanged = true;
				oldValue = cached;
				if (oldValues && !(key in oldValues)) oldValues[key] = cached;
				this.cache[key] = value;
			}
		}
		return {
			valueChanged,
			oldValue
		};
	}
};
/**
// Overrides a WebGL2RenderingContext state "getter" function
// to return values directly from cache
* @param gl
* @param functionName
*/
function installGetterOverride(gl, functionName) {
	const originalGetterFunc = gl[functionName].bind(gl);
	gl[functionName] = function get(pname) {
		if (pname === void 0 || NON_CACHE_PARAMETERS.has(pname)) return originalGetterFunc(pname);
		const glState = WebGLStateTracker.get(gl);
		if (!(pname in glState.cache)) glState.cache[pname] = originalGetterFunc(pname);
		return glState.enable ? glState.cache[pname] : originalGetterFunc(pname);
	};
	Object.defineProperty(gl[functionName], "name", {
		value: `${functionName}-from-cache`,
		configurable: false
	});
}
/**
// Overrides a WebGL2RenderingContext state "setter" function
// to call a setter spy before the actual setter. Allows us to keep a cache
// updated with a copy of the WebGL context state.
* @param gl
* @param functionName
* @param setter
* @returns
*/
function installSetterSpy(gl, functionName, setter) {
	if (!gl[functionName]) return;
	const originalSetterFunc = gl[functionName].bind(gl);
	gl[functionName] = function set(...params) {
		const { valueChanged, oldValue } = setter(WebGLStateTracker.get(gl)._updateCache, ...params);
		if (valueChanged) originalSetterFunc(...params);
		return oldValue;
	};
	Object.defineProperty(gl[functionName], "name", {
		value: `${functionName}-to-cache`,
		configurable: false
	});
}
function installProgramSpy(gl) {
	const originalUseProgram = gl.useProgram.bind(gl);
	gl.useProgram = function useProgramLuma(handle) {
		const glState = WebGLStateTracker.get(gl);
		if (glState.program !== handle) {
			originalUseProgram(handle);
			glState.program = handle;
		}
	};
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/context/helpers/create-browser-context.js
/**
* Create a WebGL context for a canvas
* Note calling this multiple time on the same canvas does return the same context
* @param canvas A canvas element or offscreen canvas
*/
function createBrowserContext(canvas, props, webglContextAttributes) {
	let errorMessage = "";
	const onCreateError = (event) => {
		const statusMessage = event.statusMessage;
		if (statusMessage) errorMessage ||= statusMessage;
	};
	canvas.addEventListener("webglcontextcreationerror", onCreateError, false);
	const allowSoftwareRenderer = webglContextAttributes.failIfMajorPerformanceCaveat !== true;
	const webglProps = {
		preserveDrawingBuffer: true,
		...webglContextAttributes,
		failIfMajorPerformanceCaveat: true
	};
	let gl = null;
	try {
		gl ||= canvas.getContext("webgl2", webglProps);
		if (!gl && webglProps.failIfMajorPerformanceCaveat) errorMessage ||= "Only software GPU is available. Set `failIfMajorPerformanceCaveat: false` to allow.";
		let softwareRenderer = false;
		if (!gl && allowSoftwareRenderer) {
			webglProps.failIfMajorPerformanceCaveat = false;
			gl = canvas.getContext("webgl2", webglProps);
			softwareRenderer = true;
		}
		if (!gl) {
			gl = canvas.getContext("webgl", {});
			if (gl) {
				gl = null;
				errorMessage ||= "Your browser only supports WebGL1";
			}
		}
		if (!gl) {
			errorMessage ||= "Your browser does not support WebGL";
			throw new Error(`Failed to create WebGL context: ${errorMessage}`);
		}
		const luma = getWebGLContextData(gl);
		luma.softwareRenderer = softwareRenderer;
		const { onContextLost, onContextRestored } = props;
		canvas.addEventListener("webglcontextlost", (event) => onContextLost(event), false);
		canvas.addEventListener("webglcontextrestored", (event) => onContextRestored(event), false);
		return gl;
	} finally {
		canvas.removeEventListener("webglcontextcreationerror", onCreateError, false);
	}
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/context/helpers/webgl-extensions.js
/** Ensure extensions are only requested once */
function getWebGLExtension(gl, name, extensions) {
	if (extensions[name] === void 0) extensions[name] = gl.getExtension(name) || null;
	return extensions[name];
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/device-helpers/webgl-device-info.js
/** @returns strings identifying the GPU vendor and driver. */
function getDeviceInfo(gl, extensions) {
	const vendorMasked = gl.getParameter(7936);
	const rendererMasked = gl.getParameter(7937);
	getWebGLExtension(gl, "WEBGL_debug_renderer_info", extensions);
	const ext = extensions.WEBGL_debug_renderer_info;
	const vendorUnmasked = gl.getParameter(ext ? ext.UNMASKED_VENDOR_WEBGL : 7936);
	const rendererUnmasked = gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : 7937);
	const vendor = vendorUnmasked || vendorMasked;
	const renderer = rendererUnmasked || rendererMasked;
	const version = gl.getParameter(7938);
	const gpu = identifyGPUVendor(vendor, renderer);
	const gpuBackend = identifyGPUBackend(vendor, renderer);
	return {
		type: "webgl",
		gpu,
		gpuType: identifyGPUType(vendor, renderer),
		gpuBackend,
		vendor,
		renderer,
		version,
		shadingLanguage: "glsl",
		shadingLanguageVersion: 300
	};
}
/** "Sniff" the GPU type from the info. This works best if unmasked info is available. */
function identifyGPUVendor(vendor, renderer) {
	if (/NVIDIA/i.exec(vendor) || /NVIDIA/i.exec(renderer)) return "nvidia";
	if (/INTEL/i.exec(vendor) || /INTEL/i.exec(renderer)) return "intel";
	if (/Apple/i.exec(vendor) || /Apple/i.exec(renderer)) return "apple";
	if (/AMD/i.exec(vendor) || /AMD/i.exec(renderer) || /ATI/i.exec(vendor) || /ATI/i.exec(renderer)) return "amd";
	if (/SwiftShader/i.exec(vendor) || /SwiftShader/i.exec(renderer)) return "software";
	return "unknown";
}
/** "Sniff" the GPU backend from the info. This works best if unmasked info is available. */
function identifyGPUBackend(vendor, renderer) {
	if (/Metal/i.exec(vendor) || /Metal/i.exec(renderer)) return "metal";
	if (/ANGLE/i.exec(vendor) || /ANGLE/i.exec(renderer)) return "opengl";
	return "unknown";
}
function identifyGPUType(vendor, renderer) {
	if (/SwiftShader/i.exec(vendor) || /SwiftShader/i.exec(renderer)) return "cpu";
	switch (identifyGPUVendor(vendor, renderer)) {
		case "apple": return isAppleSiliconGPU(vendor, renderer) ? "integrated" : "unknown";
		case "intel": return "integrated";
		case "software": return "cpu";
		case "unknown": return "unknown";
		default: return "discrete";
	}
}
function isAppleSiliconGPU(vendor, renderer) {
	return /Apple (M\d|A\d|GPU)/i.test(`${vendor} ${renderer}`);
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/converters/webgl-vertex-formats.js
function getGLFromVertexType(dataType) {
	switch (dataType) {
		case "uint8": return 5121;
		case "sint8": return 5120;
		case "unorm8": return 5121;
		case "snorm8": return 5120;
		case "uint16": return 5123;
		case "sint16": return 5122;
		case "unorm16": return 5123;
		case "snorm16": return 5122;
		case "uint32": return 5125;
		case "sint32": return 5124;
		case "float16": return 5131;
		case "float32": return 5126;
	}
	throw new Error(String(dataType));
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/converters/webgl-texture-table.js
var X_S3TC = "WEBGL_compressed_texture_s3tc";
var X_S3TC_SRGB = "WEBGL_compressed_texture_s3tc_srgb";
var X_RGTC = "EXT_texture_compression_rgtc";
var X_BPTC = "EXT_texture_compression_bptc";
var X_ETC2 = "WEBGL_compressed_texture_etc";
var X_ASTC = "WEBGL_compressed_texture_astc";
var X_ETC1 = "WEBGL_compressed_texture_etc1";
var X_PVRTC = "WEBGL_compressed_texture_pvrtc";
var X_ATC = "WEBGL_compressed_texture_atc";
var EXT_texture_norm16 = "EXT_texture_norm16";
var EXT_render_snorm = "EXT_render_snorm";
var EXT_color_buffer_float = "EXT_color_buffer_float";
var SNORM8_COLOR_RENDERABLE = "snorm8-renderable-webgl";
var NORM16_COLOR_RENDERABLE = "norm16-renderable-webgl";
var SNORM16_COLOR_RENDERABLE = "snorm16-renderable-webgl";
var FLOAT16_COLOR_RENDERABLE = "float16-renderable-webgl";
var FLOAT32_COLOR_RENDERABLE = "float32-renderable-webgl";
var RGB9E5UFLOAT_COLOR_RENDERABLE = "rgb9e5ufloat-renderable-webgl";
var TEXTURE_FEATURES = {
	"float32-renderable-webgl": { extensions: [EXT_color_buffer_float] },
	"float16-renderable-webgl": { extensions: ["EXT_color_buffer_half_float"] },
	"rgb9e5ufloat-renderable-webgl": { extensions: ["WEBGL_render_shared_exponent"] },
	"snorm8-renderable-webgl": { extensions: [EXT_render_snorm] },
	"norm16-webgl": { extensions: [EXT_texture_norm16] },
	"norm16-renderable-webgl": { features: ["norm16-webgl"] },
	"snorm16-renderable-webgl": {
		features: ["norm16-webgl"],
		extensions: [EXT_render_snorm]
	},
	"float32-filterable": { extensions: ["OES_texture_float_linear"] },
	"float16-filterable-webgl": { extensions: ["OES_texture_half_float_linear"] },
	"texture-filterable-anisotropic-webgl": { extensions: ["EXT_texture_filter_anisotropic"] },
	"texture-blend-float-webgl": { extensions: ["EXT_float_blend"] },
	"texture-compression-bc": { extensions: [
		X_S3TC,
		X_S3TC_SRGB,
		X_RGTC,
		X_BPTC
	] },
	"texture-compression-bc5-webgl": { extensions: [X_RGTC] },
	"texture-compression-bc7-webgl": { extensions: [X_BPTC] },
	"texture-compression-etc2": { extensions: [X_ETC2] },
	"texture-compression-astc": { extensions: [X_ASTC] },
	"texture-compression-etc1-webgl": { extensions: [X_ETC1] },
	"texture-compression-pvrtc-webgl": { extensions: [X_PVRTC] },
	"texture-compression-atc-webgl": { extensions: [X_ATC] }
};
function isTextureFeature(feature) {
	return feature in TEXTURE_FEATURES;
}
/** Checks a texture feature (for Device.features). Mainly compressed texture support */
function checkTextureFeature(gl, feature, extensions) {
	return hasTextureFeature(gl, feature, extensions, /* @__PURE__ */ new Set());
}
function hasTextureFeature(gl, feature, extensions, seenFeatures) {
	const definition = TEXTURE_FEATURES[feature];
	if (!definition) return false;
	if (seenFeatures.has(feature)) return false;
	seenFeatures.add(feature);
	const hasDependentFeatures = (definition.features || []).every((dependentFeature) => hasTextureFeature(gl, dependentFeature, extensions, seenFeatures));
	seenFeatures.delete(feature);
	if (!hasDependentFeatures) return false;
	return (definition.extensions || []).every((extension) => Boolean(getWebGLExtension(gl, extension, extensions)));
}
/**
* Texture format data -
* Exported but can change without notice
*/
var WEBGL_TEXTURE_FORMATS = {
	"r8unorm": {
		gl: 33321,
		rb: true
	},
	"r8snorm": {
		gl: 36756,
		r: SNORM8_COLOR_RENDERABLE
	},
	"r8uint": {
		gl: 33330,
		rb: true
	},
	"r8sint": {
		gl: 33329,
		rb: true
	},
	"rg8unorm": {
		gl: 33323,
		rb: true
	},
	"rg8snorm": {
		gl: 36757,
		r: SNORM8_COLOR_RENDERABLE
	},
	"rg8uint": {
		gl: 33336,
		rb: true
	},
	"rg8sint": {
		gl: 33335,
		rb: true
	},
	"r16uint": {
		gl: 33332,
		rb: true
	},
	"r16sint": {
		gl: 33331,
		rb: true
	},
	"r16float": {
		gl: 33325,
		rb: true,
		r: FLOAT16_COLOR_RENDERABLE
	},
	"r16unorm": {
		gl: 33322,
		rb: true,
		r: NORM16_COLOR_RENDERABLE
	},
	"r16snorm": {
		gl: 36760,
		r: SNORM16_COLOR_RENDERABLE
	},
	"rgba4unorm-webgl": {
		gl: 32854,
		rb: true
	},
	"rgb565unorm-webgl": {
		gl: 36194,
		rb: true
	},
	"rgb5a1unorm-webgl": {
		gl: 32855,
		rb: true
	},
	"rgb8unorm-webgl": { gl: 32849 },
	"rgb8snorm-webgl": { gl: 36758 },
	"rgba8unorm": { gl: 32856 },
	"rgba8unorm-srgb": { gl: 35907 },
	"rgba8snorm": {
		gl: 36759,
		r: SNORM8_COLOR_RENDERABLE
	},
	"rgba8uint": { gl: 36220 },
	"rgba8sint": { gl: 36238 },
	"bgra8unorm": {},
	"bgra8unorm-srgb": {},
	"rg16uint": { gl: 33338 },
	"rg16sint": { gl: 33337 },
	"rg16float": {
		gl: 33327,
		rb: true,
		r: FLOAT16_COLOR_RENDERABLE
	},
	"rg16unorm": {
		gl: 33324,
		r: NORM16_COLOR_RENDERABLE
	},
	"rg16snorm": {
		gl: 36761,
		r: SNORM16_COLOR_RENDERABLE
	},
	"r32uint": {
		gl: 33334,
		rb: true
	},
	"r32sint": {
		gl: 33333,
		rb: true
	},
	"r32float": {
		gl: 33326,
		r: FLOAT32_COLOR_RENDERABLE
	},
	"rgb9e5ufloat": {
		gl: 35901,
		r: RGB9E5UFLOAT_COLOR_RENDERABLE
	},
	"rg11b10ufloat": {
		gl: 35898,
		rb: true
	},
	"rgb10a2unorm": {
		gl: 32857,
		rb: true
	},
	"rgb10a2uint": {
		gl: 36975,
		rb: true
	},
	"rgb16unorm-webgl": {
		gl: 32852,
		r: false
	},
	"rgb16snorm-webgl": {
		gl: 36762,
		r: false
	},
	"rg32uint": {
		gl: 33340,
		rb: true
	},
	"rg32sint": {
		gl: 33339,
		rb: true
	},
	"rg32float": {
		gl: 33328,
		rb: true,
		r: FLOAT32_COLOR_RENDERABLE
	},
	"rgba16uint": {
		gl: 36214,
		rb: true
	},
	"rgba16sint": {
		gl: 36232,
		rb: true
	},
	"rgba16float": {
		gl: 34842,
		r: FLOAT16_COLOR_RENDERABLE
	},
	"rgba16unorm": {
		gl: 32859,
		rb: true,
		r: NORM16_COLOR_RENDERABLE
	},
	"rgba16snorm": {
		gl: 36763,
		r: SNORM16_COLOR_RENDERABLE
	},
	"rgb32float-webgl": {
		gl: 34837,
		x: EXT_color_buffer_float,
		r: FLOAT32_COLOR_RENDERABLE,
		dataFormat: 6407,
		types: [5126]
	},
	"rgba32uint": {
		gl: 36208,
		rb: true
	},
	"rgba32sint": {
		gl: 36226,
		rb: true
	},
	"rgba32float": {
		gl: 34836,
		rb: true,
		r: FLOAT32_COLOR_RENDERABLE
	},
	"stencil8": {
		gl: 36168,
		rb: true
	},
	"depth16unorm": {
		gl: 33189,
		dataFormat: 6402,
		types: [5123],
		rb: true
	},
	"depth24plus": {
		gl: 33190,
		dataFormat: 6402,
		types: [5125]
	},
	"depth32float": {
		gl: 36012,
		dataFormat: 6402,
		types: [5126],
		rb: true
	},
	"depth24plus-stencil8": {
		gl: 35056,
		rb: true,
		depthTexture: true,
		dataFormat: 34041,
		types: [34042]
	},
	"depth32float-stencil8": {
		gl: 36013,
		dataFormat: 34041,
		types: [36269],
		rb: true
	},
	"bc1-rgb-unorm-webgl": {
		gl: 33776,
		x: X_S3TC
	},
	"bc1-rgb-unorm-srgb-webgl": {
		gl: 35916,
		x: X_S3TC_SRGB
	},
	"bc1-rgba-unorm": {
		gl: 33777,
		x: X_S3TC
	},
	"bc1-rgba-unorm-srgb": {
		gl: 35916,
		x: X_S3TC_SRGB
	},
	"bc2-rgba-unorm": {
		gl: 33778,
		x: X_S3TC
	},
	"bc2-rgba-unorm-srgb": {
		gl: 35918,
		x: X_S3TC_SRGB
	},
	"bc3-rgba-unorm": {
		gl: 33779,
		x: X_S3TC
	},
	"bc3-rgba-unorm-srgb": {
		gl: 35919,
		x: X_S3TC_SRGB
	},
	"bc4-r-unorm": {
		gl: 36283,
		x: X_RGTC
	},
	"bc4-r-snorm": {
		gl: 36284,
		x: X_RGTC
	},
	"bc5-rg-unorm": {
		gl: 36285,
		x: X_RGTC
	},
	"bc5-rg-snorm": {
		gl: 36286,
		x: X_RGTC
	},
	"bc6h-rgb-ufloat": {
		gl: 36495,
		x: X_BPTC
	},
	"bc6h-rgb-float": {
		gl: 36494,
		x: X_BPTC
	},
	"bc7-rgba-unorm": {
		gl: 36492,
		x: X_BPTC
	},
	"bc7-rgba-unorm-srgb": {
		gl: 36493,
		x: X_BPTC
	},
	"etc2-rgb8unorm": { gl: 37492 },
	"etc2-rgb8unorm-srgb": { gl: 37494 },
	"etc2-rgb8a1unorm": { gl: 37496 },
	"etc2-rgb8a1unorm-srgb": { gl: 37497 },
	"etc2-rgba8unorm": { gl: 37493 },
	"etc2-rgba8unorm-srgb": { gl: 37495 },
	"eac-r11unorm": { gl: 37488 },
	"eac-r11snorm": { gl: 37489 },
	"eac-rg11unorm": { gl: 37490 },
	"eac-rg11snorm": { gl: 37491 },
	"astc-4x4-unorm": { gl: 37808 },
	"astc-4x4-unorm-srgb": { gl: 37840 },
	"astc-5x4-unorm": { gl: 37809 },
	"astc-5x4-unorm-srgb": { gl: 37841 },
	"astc-5x5-unorm": { gl: 37810 },
	"astc-5x5-unorm-srgb": { gl: 37842 },
	"astc-6x5-unorm": { gl: 37811 },
	"astc-6x5-unorm-srgb": { gl: 37843 },
	"astc-6x6-unorm": { gl: 37812 },
	"astc-6x6-unorm-srgb": { gl: 37844 },
	"astc-8x5-unorm": { gl: 37813 },
	"astc-8x5-unorm-srgb": { gl: 37845 },
	"astc-8x6-unorm": { gl: 37814 },
	"astc-8x6-unorm-srgb": { gl: 37846 },
	"astc-8x8-unorm": { gl: 37815 },
	"astc-8x8-unorm-srgb": { gl: 37847 },
	"astc-10x5-unorm": { gl: 37816 },
	"astc-10x5-unorm-srgb": { gl: 37848 },
	"astc-10x6-unorm": { gl: 37817 },
	"astc-10x6-unorm-srgb": { gl: 37849 },
	"astc-10x8-unorm": { gl: 37818 },
	"astc-10x8-unorm-srgb": { gl: 37850 },
	"astc-10x10-unorm": { gl: 37819 },
	"astc-10x10-unorm-srgb": { gl: 37851 },
	"astc-12x10-unorm": { gl: 37820 },
	"astc-12x10-unorm-srgb": { gl: 37852 },
	"astc-12x12-unorm": { gl: 37821 },
	"astc-12x12-unorm-srgb": { gl: 37853 },
	"pvrtc-rgb4unorm-webgl": { gl: 35840 },
	"pvrtc-rgba4unorm-webgl": { gl: 35842 },
	"pvrtc-rgb2unorm-webgl": { gl: 35841 },
	"pvrtc-rgba2unorm-webgl": { gl: 35843 },
	"etc1-rbg-unorm-webgl": { gl: 36196 },
	"atc-rgb-unorm-webgl": { gl: 35986 },
	"atc-rgba-unorm-webgl": { gl: 35986 },
	"atc-rgbai-unorm-webgl": { gl: 34798 }
};
/** Checks if a texture format is supported, renderable, filterable etc */
function getTextureFormatCapabilitiesWebGL(gl, formatSupport, extensions) {
	let supported = formatSupport.create;
	const webglFormatInfo = WEBGL_TEXTURE_FORMATS[formatSupport.format];
	if (webglFormatInfo?.gl === void 0) supported = false;
	if (webglFormatInfo?.x) supported = supported && Boolean(getWebGLExtension(gl, webglFormatInfo.x, extensions));
	if (formatSupport.format === "stencil8") supported = false;
	const renderFeatureSupported = webglFormatInfo?.r === false ? false : webglFormatInfo?.r === void 0 || checkTextureFeature(gl, webglFormatInfo.r, extensions);
	const renderable = supported && formatSupport.render && renderFeatureSupported && isColorRenderableTextureFormat(gl, formatSupport.format, extensions);
	return {
		format: formatSupport.format,
		create: supported && formatSupport.create,
		render: renderable,
		filter: supported && formatSupport.filter,
		blend: supported && formatSupport.blend,
		store: supported && formatSupport.store
	};
}
function isColorRenderableTextureFormat(gl, format, extensions) {
	const webglFormatInfo = WEBGL_TEXTURE_FORMATS[format];
	const internalFormat = webglFormatInfo?.gl;
	if (internalFormat === void 0) return false;
	if (webglFormatInfo?.x && !getWebGLExtension(gl, webglFormatInfo.x, extensions)) return false;
	const previousTexture = gl.getParameter(32873);
	const previousFramebuffer = gl.getParameter(36006);
	const texture = gl.createTexture();
	const framebuffer = gl.createFramebuffer();
	if (!texture || !framebuffer) return false;
	const noError = 0;
	let error = Number(gl.getError());
	while (error !== noError) error = gl.getError();
	let renderable = false;
	try {
		gl.bindTexture(3553, texture);
		gl.texStorage2D(3553, 1, internalFormat, 1, 1);
		if (Number(gl.getError()) !== noError) return false;
		gl.bindFramebuffer(36160, framebuffer);
		gl.framebufferTexture2D(36160, 36064, 3553, texture, 0);
		renderable = Number(gl.checkFramebufferStatus(36160)) === 36053 && Number(gl.getError()) === noError;
	} finally {
		gl.bindFramebuffer(36160, previousFramebuffer);
		gl.deleteFramebuffer(framebuffer);
		gl.bindTexture(3553, previousTexture);
		gl.deleteTexture(texture);
	}
	return renderable;
}
/** Get parameters necessary to work with format in WebGL: internalFormat, dataFormat, type, compressed, */
function getTextureFormatWebGL(format) {
	const formatData = WEBGL_TEXTURE_FORMATS[format];
	const webglFormat = convertTextureFormatToGL(format);
	const decoded = textureFormatDecoder.getInfo(format);
	if (decoded.compressed) formatData.dataFormat = webglFormat;
	return {
		internalFormat: webglFormat,
		format: formatData?.dataFormat || getWebGLPixelDataFormat(decoded.channels, decoded.integer, decoded.normalized, webglFormat),
		type: decoded.dataType ? getGLFromVertexType(decoded.dataType) : formatData?.types?.[0] || 5121,
		compressed: decoded.compressed || false
	};
}
function getDepthStencilAttachmentWebGL(format) {
	switch (textureFormatDecoder.getInfo(format).attachment) {
		case "depth": return 36096;
		case "stencil": return 36128;
		case "depth-stencil": return 33306;
		default: throw new Error(`Not a depth stencil format: ${format}`);
	}
}
function getWebGLPixelDataFormat(channels, integer, normalized, format) {
	if (format === 6408 || format === 6407) return format;
	switch (channels) {
		case "r": return integer && !normalized ? 36244 : 6403;
		case "rg": return integer && !normalized ? 33320 : 33319;
		case "rgb": return integer && !normalized ? 36248 : 6407;
		case "rgba": return integer && !normalized ? 36249 : 6408;
		case "bgra": throw new Error("bgra pixels not supported by WebGL");
		default: return 6408;
	}
}
/**
* Map WebGPU style texture format strings to GL constants
*/
function convertTextureFormatToGL(format) {
	const webglFormat = WEBGL_TEXTURE_FORMATS[format]?.gl;
	if (webglFormat === void 0) throw new Error(`Unsupported texture format ${format}`);
	return webglFormat;
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/device-helpers/webgl-device-features.js
/**
* Defines luma.gl "feature" names and semantics
* when value is 'string' it is the name of the extension that enables this feature
*/
var WEBGL_FEATURES = {
	"depth-clip-control": "EXT_depth_clamp",
	"timestamp-query": "EXT_disjoint_timer_query_webgl2",
	"compilation-status-async-webgl": "KHR_parallel_shader_compile",
	"polygon-mode-webgl": "WEBGL_polygon_mode",
	"provoking-vertex-webgl": "WEBGL_provoking_vertex",
	"shader-clip-cull-distance-webgl": "WEBGL_clip_cull_distance",
	"shader-noperspective-interpolation-webgl": "NV_shader_noperspective_interpolation",
	"shader-conservative-depth-webgl": "EXT_conservative_depth"
};
/**
* WebGL extensions exposed as luma.gl features
* To minimize GL log noise and improve performance, this class ensures that
* - WebGL extensions are not queried until the corresponding feature is checked.
* - WebGL extensions are only queried once.
*/
var WebGLDeviceFeatures = class extends DeviceFeatures {
	gl;
	extensions;
	testedFeatures = /* @__PURE__ */ new Set();
	constructor(gl, extensions, disabledFeatures) {
		super([], disabledFeatures);
		this.gl = gl;
		this.extensions = extensions;
		getWebGLExtension(gl, "EXT_color_buffer_float", extensions);
	}
	*[Symbol.iterator]() {
		const features = this.getFeatures();
		for (const feature of features) if (this.has(feature)) yield feature;
		return [];
	}
	has(feature) {
		if (this.disabledFeatures?.[feature]) return false;
		if (!this.testedFeatures.has(feature)) {
			this.testedFeatures.add(feature);
			if (isTextureFeature(feature) && checkTextureFeature(this.gl, feature, this.extensions)) this.features.add(feature);
			if (this.getWebGLFeature(feature)) this.features.add(feature);
		}
		return this.features.has(feature);
	}
	initializeFeatures() {
		const features = this.getFeatures().filter((feature) => feature !== "polygon-mode-webgl");
		for (const feature of features) this.has(feature);
	}
	getFeatures() {
		return [...Object.keys(WEBGL_FEATURES), ...Object.keys(TEXTURE_FEATURES)];
	}
	/** Extract all WebGL features */
	getWebGLFeature(feature) {
		const featureInfo = WEBGL_FEATURES[feature];
		return typeof featureInfo === "string" ? Boolean(getWebGLExtension(this.gl, featureInfo, this.extensions)) : Boolean(featureInfo);
	}
};
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/device-helpers/webgl-device-limits.js
var WebGLDeviceLimits = class extends DeviceLimits {
	get maxTextureDimension1D() {
		return 0;
	}
	get maxTextureDimension2D() {
		return this.getParameter(3379);
	}
	get maxTextureDimension3D() {
		return this.getParameter(32883);
	}
	get maxTextureArrayLayers() {
		return this.getParameter(35071);
	}
	get maxBindGroups() {
		return 0;
	}
	get maxDynamicUniformBuffersPerPipelineLayout() {
		return 0;
	}
	get maxDynamicStorageBuffersPerPipelineLayout() {
		return 0;
	}
	get maxSampledTexturesPerShaderStage() {
		return this.getParameter(35660);
	}
	get maxSamplersPerShaderStage() {
		return this.getParameter(35661);
	}
	get maxStorageBuffersPerShaderStage() {
		return 0;
	}
	get maxStorageTexturesPerShaderStage() {
		return 0;
	}
	get maxUniformBuffersPerShaderStage() {
		return this.getParameter(35375);
	}
	get maxUniformBufferBindingSize() {
		return this.getParameter(35376);
	}
	get maxStorageBufferBindingSize() {
		return 0;
	}
	get minUniformBufferOffsetAlignment() {
		return this.getParameter(35380);
	}
	get minStorageBufferOffsetAlignment() {
		return 0;
	}
	get maxVertexBuffers() {
		return 16;
	}
	get maxVertexAttributes() {
		return this.getParameter(34921);
	}
	get maxVertexBufferArrayStride() {
		return 2048;
	}
	get maxInterStageShaderVariables() {
		return this.getParameter(35659);
	}
	get maxComputeWorkgroupStorageSize() {
		return 0;
	}
	get maxComputeInvocationsPerWorkgroup() {
		return 0;
	}
	get maxComputeWorkgroupSizeX() {
		return 0;
	}
	get maxComputeWorkgroupSizeY() {
		return 0;
	}
	get maxComputeWorkgroupSizeZ() {
		return 0;
	}
	get maxComputeWorkgroupsPerDimension() {
		return 0;
	}
	gl;
	limits = {};
	constructor(gl) {
		super();
		this.gl = gl;
	}
	getParameter(parameter) {
		if (this.limits[parameter] === void 0) this.limits[parameter] = this.gl.getParameter(parameter);
		return this.limits[parameter] || 0;
	}
};
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/resources/webgl-framebuffer.js
/** luma.gl Framebuffer, WebGL implementation  */
var WEBGLFramebuffer = class extends Framebuffer {
	device;
	gl;
	handle;
	colorAttachments = [];
	depthStencilAttachment = null;
	constructor(device, props) {
		super(device, props);
		const isDefaultFramebuffer = props.handle === null;
		this.device = device;
		this.gl = device.gl;
		this.handle = this.props.handle || isDefaultFramebuffer ? this.props.handle : this.gl.createFramebuffer();
		if (!isDefaultFramebuffer) {
			device._setWebGLDebugMetadata(this.handle, this, { spector: this.props });
			if (!props.handle) {
				this.autoCreateAttachmentTextures();
				this.updateAttachments();
			}
		}
	}
	/** destroys any auto created resources etc. */
	destroy() {
		super.destroy();
		if (!this.destroyed && this.handle !== null && !this.props.handle) this.gl.deleteFramebuffer(this.handle);
	}
	updateAttachments() {
		/** Attach from a map of attachments */
		const prevHandle = this.gl.bindFramebuffer(36160, this.handle);
		for (let i = 0; i < this.colorAttachments.length; ++i) {
			const attachment = this.colorAttachments[i];
			if (attachment) {
				const attachmentPoint = 36064 + i;
				this._attachTextureView(attachmentPoint, attachment);
			}
		}
		if (this.depthStencilAttachment) {
			const attachmentPoint = getDepthStencilAttachmentWebGL(this.depthStencilAttachment.props.format);
			this._attachTextureView(attachmentPoint, this.depthStencilAttachment);
		}
		/** Check the status */
		if (this.device.props.debug) {
			const status = this.gl.checkFramebufferStatus(36160);
			if (status !== 36053) throw new Error(`Framebuffer ${_getFrameBufferStatus(status)}`);
		}
		this.gl.bindFramebuffer(36160, prevHandle);
	}
	/** In WebGL we must use renderbuffers for depth/stencil attachments (unless we have extensions) */
	/**
	* @param attachment
	* @param texture
	* @param layer = 0 - index into WEBGLTextureArray and Texture3D or face for `TextureCubeMap`
	* @param level = 0 - mipmapLevel
	*/
	_attachTextureView(attachment, textureView) {
		const { gl } = this.device;
		const { texture } = textureView;
		const level = textureView.props.baseMipLevel;
		const layer = textureView.props.baseArrayLayer;
		gl.bindTexture(texture.glTarget, texture.handle);
		switch (texture.glTarget) {
			case 35866:
			case 32879:
				gl.framebufferTextureLayer(36160, attachment, texture.handle, level, layer);
				break;
			case 34067:
				const face = mapIndexToCubeMapFace(layer);
				gl.framebufferTexture2D(36160, attachment, face, texture.handle, level);
				break;
			case 3553:
				gl.framebufferTexture2D(36160, attachment, 3553, texture.handle, level);
				break;
			default: throw new Error("Illegal texture type");
		}
		gl.bindTexture(texture.glTarget, null);
	}
	/** Default framebuffer resize is managed by canvas size and should be a no-op. */
	resizeAttachments(width, height) {
		if (this.handle === null) {
			this.width = width;
			this.height = height;
			return;
		}
		super.resizeAttachments(width, height);
	}
};
function mapIndexToCubeMapFace(layer) {
	return layer < 34069 ? layer + 34069 : layer;
}
function _getFrameBufferStatus(status) {
	switch (status) {
		case 36053: return "success";
		case 36054: return "Mismatched attachments";
		case 36055: return "No attachments";
		case 36057: return "Height/width mismatch";
		case 36061: return "Unsupported or split attachments";
		case 36182: return "Samples mismatch";
		default: return `${status}`;
	}
}
/**
* Attachment resize is expected to be a noop if size is same
*
protected override resizeAttachments(width: number, height: number): this {
// for default framebuffer, just update the stored size
if (this.handle === null) {
// assert(width === undefined && height === undefined);
this.width = this.gl.drawingBufferWidth;
this.height = this.gl.drawingBufferHeight;
return this;
}

if (width === undefined) {
width = this.gl.drawingBufferWidth;
}
if (height === undefined) {
height = this.gl.drawingBufferHeight;
}

// TODO Not clear that this is better than default destroy/create implementation

for (const colorAttachment of this.colorAttachments) {
colorAttachment.texture.clone({width, height});
}
if (this.depthStencilAttachment) {
this.depthStencilAttachment.texture.resize({width, height});
}
return this;
}
*/
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/webgl-canvas-context.js
/**
* A WebGL Canvas Context which manages the canvas and handles drawing buffer resizing etc
*/
var WebGLCanvasContext = class extends CanvasContext {
	device;
	handle = null;
	_framebuffer = null;
	get [Symbol.toStringTag]() {
		return "WebGLCanvasContext";
	}
	constructor(device, props) {
		super(props);
		this.device = device;
		this._setAutoCreatedCanvasId(`${this.device.id}-canvas`);
		this._configureDevice();
	}
	_configureDevice() {
		if (this.drawingBufferWidth !== this._framebuffer?.width || this.drawingBufferHeight !== this._framebuffer?.height) this._framebuffer?.resize([this.drawingBufferWidth, this.drawingBufferHeight]);
	}
	_getCurrentFramebuffer() {
		this._framebuffer ||= new WEBGLFramebuffer(this.device, {
			id: "canvas-context-framebuffer",
			handle: null,
			width: this.drawingBufferWidth,
			height: this.drawingBufferHeight
		});
		return this._framebuffer;
	}
};
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/webgl-presentation-context.js
/**
* Tracks a non-WebGL destination canvas while rendering into the device's default canvas context.
*/
var WebGLPresentationContext = class extends PresentationContext {
	device;
	handle = null;
	context2d;
	get [Symbol.toStringTag]() {
		return "WebGLPresentationContext";
	}
	constructor(device, props = {}) {
		super(props);
		this.device = device;
		const contextLabel = `${this[Symbol.toStringTag]}(${this.id})`;
		if (!this.device.getDefaultCanvasContext().offscreenCanvas) throw new Error(`${contextLabel}: WebGL PresentationContext requires the default CanvasContext canvas to be an OffscreenCanvas`);
		const context2d = this.canvas.getContext("2d");
		if (!context2d) throw new Error(`${contextLabel}: Failed to create 2d presentation context`);
		this.context2d = context2d;
		this._setAutoCreatedCanvasId(`${this.device.id}-presentation-canvas`);
		this._configureDevice();
		this._startObservers();
	}
	present() {
		this._resizeDrawingBufferIfNeeded();
		this.device.submit();
		const defaultCanvasContext = this.device.getDefaultCanvasContext();
		const [sourceWidth, sourceHeight] = defaultCanvasContext.getDrawingBufferSize();
		if (this.drawingBufferWidth === 0 || this.drawingBufferHeight === 0 || sourceWidth === 0 || sourceHeight === 0 || defaultCanvasContext.canvas.width === 0 || defaultCanvasContext.canvas.height === 0) return;
		if (sourceWidth !== this.drawingBufferWidth || sourceHeight !== this.drawingBufferHeight || defaultCanvasContext.canvas.width !== this.drawingBufferWidth || defaultCanvasContext.canvas.height !== this.drawingBufferHeight) throw new Error(`${this[Symbol.toStringTag]}(${this.id}): Default canvas context size ${sourceWidth}x${sourceHeight} does not match presentation size ${this.drawingBufferWidth}x${this.drawingBufferHeight}`);
		this.context2d.clearRect(0, 0, this.drawingBufferWidth, this.drawingBufferHeight);
		this.context2d.drawImage(defaultCanvasContext.canvas, 0, 0);
	}
	_configureDevice() {}
	_getCurrentFramebuffer(options) {
		const defaultCanvasContext = this.device.getDefaultCanvasContext();
		defaultCanvasContext.setDrawingBufferSize(this.drawingBufferWidth, this.drawingBufferHeight);
		return defaultCanvasContext.getCurrentFramebuffer(options);
	}
};
//#endregion
//#region node_modules/@luma.gl/webgl/dist/utils/uid.js
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
//#region node_modules/@luma.gl/webgl/dist/adapter/resources/webgl-buffer.js
/** WebGL Buffer interface */
var WEBGLBuffer = class extends Buffer {
	device;
	gl;
	handle;
	/** Target in OpenGL defines the type of buffer */
	glTarget;
	/** Usage is a hint on how frequently the buffer will be updates */
	glUsage;
	/** Index type is needed when issuing draw calls, so we pre-compute it */
	glIndexType = 5123;
	/** Number of bytes allocated on the GPU for this buffer */
	byteLength = 0;
	/** Number of bytes used */
	bytesUsed = 0;
	constructor(device, props = {}) {
		super(device, props);
		this.device = device;
		this.gl = this.device.gl;
		const handle = typeof props === "object" ? props.handle : void 0;
		this.handle = handle || this.gl.createBuffer();
		device._setWebGLDebugMetadata(this.handle, this, { spector: {
			...this.props,
			data: typeof this.props.data
		} });
		this.glTarget = getWebGLTarget(this.props.usage);
		this.glUsage = getWebGLUsage(this.props.usage);
		this.glIndexType = this.props.indexType === "uint32" ? 5125 : 5123;
		if (props.data) this._initWithData(props.data, props.byteOffset, props.byteLength);
		else this._initWithByteLength(props.byteLength || 0);
	}
	destroy() {
		if (!this.destroyed && this.handle) {
			this.removeStats();
			if (!this.props.handle) {
				this.trackDeallocatedMemory();
				this.gl.deleteBuffer(this.handle);
			} else this.trackDeallocatedReferencedMemory("Buffer");
			this.destroyed = true;
			this.handle = null;
		}
	}
	/** Allocate a new buffer and initialize to contents of typed array */
	_initWithData(data, byteOffset = 0, byteLength = data.byteLength + byteOffset) {
		const glTarget = this.glTarget;
		this.gl.bindBuffer(glTarget, this.handle);
		this.gl.bufferData(glTarget, byteLength, this.glUsage);
		this.gl.bufferSubData(glTarget, byteOffset, data);
		this.gl.bindBuffer(glTarget, null);
		this.bytesUsed = byteLength;
		this.byteLength = byteLength;
		this._setDebugData(data, byteOffset, byteLength);
		if (!this.props.handle) this.trackAllocatedMemory(byteLength);
		else this.trackReferencedMemory(byteLength, "Buffer");
	}
	_initWithByteLength(byteLength) {
		let data = byteLength;
		if (byteLength === 0) data = new Float32Array(0);
		const glTarget = this.glTarget;
		this.gl.bindBuffer(glTarget, this.handle);
		this.gl.bufferData(glTarget, data, this.glUsage);
		this.gl.bindBuffer(glTarget, null);
		this.bytesUsed = byteLength;
		this.byteLength = byteLength;
		this._setDebugData(null, 0, byteLength);
		if (!this.props.handle) this.trackAllocatedMemory(byteLength);
		else this.trackReferencedMemory(byteLength, "Buffer");
		return this;
	}
	write(data, byteOffset = 0) {
		const dataView = ArrayBuffer.isView(data) ? data : new Uint8Array(data);
		const glTarget = 36663;
		this.gl.bindBuffer(glTarget, this.handle);
		this.gl.bufferSubData(glTarget, byteOffset, dataView);
		this.gl.bindBuffer(glTarget, null);
		this._setDebugData(data, byteOffset, data.byteLength);
	}
	async mapAndWriteAsync(callback, byteOffset = 0, byteLength = this.byteLength - byteOffset) {
		const arrayBuffer = new ArrayBuffer(byteLength);
		await callback(arrayBuffer, "copied");
		this.write(arrayBuffer, byteOffset);
	}
	async readAsync(byteOffset = 0, byteLength) {
		return this.readSyncWebGL(byteOffset, byteLength);
	}
	async mapAndReadAsync(callback, byteOffset = 0, byteLength) {
		return await callback((await this.readAsync(byteOffset, byteLength)).buffer, "copied");
	}
	readSyncWebGL(byteOffset = 0, byteLength) {
		byteLength = byteLength ?? this.byteLength - byteOffset;
		const data = new Uint8Array(byteLength);
		const dstOffset = 0;
		this.gl.bindBuffer(36662, this.handle);
		this.gl.getBufferSubData(36662, byteOffset, data, dstOffset, byteLength);
		this.gl.bindBuffer(36662, null);
		this._setDebugData(data, byteOffset, byteLength);
		return data;
	}
};
/**
* Returns a WebGL buffer target
*
* @param usage
* static MAP_READ = 0x01;
* static MAP_WRITE = 0x02;
* static COPY_SRC = 0x0004;
* static COPY_DST = 0x0008;
* static INDEX = 0x0010;
* static VERTEX = 0x0020;
* static UNIFORM = 0x0040;
* static STORAGE = 0x0080;
* static INDIRECT = 0x0100;
* static QUERY_RESOLVE = 0x0200;
*
* @returns WebGL buffer targe
*
* Buffer bind points in WebGL2
* gl.COPY_READ_BUFFER: Buffer for copying from one buffer object to another.
* gl.COPY_WRITE_BUFFER: Buffer for copying from one buffer object to another.
* gl.TRANSFORM_FEEDBACK_BUFFER: Buffer for transform feedback operations.
* gl.PIXEL_PACK_BUFFER: Buffer used for pixel transfer operations.
* gl.PIXEL_UNPACK_BUFFER: Buffer used for pixel transfer operations.
*/
function getWebGLTarget(usage) {
	if (usage & Buffer.INDEX) return 34963;
	if (usage & Buffer.VERTEX) return 34962;
	if (usage & Buffer.UNIFORM) return 35345;
	return 34962;
}
/** @todo usage is not passed correctly */
function getWebGLUsage(usage) {
	if (usage & Buffer.INDEX) return 35044;
	if (usage & Buffer.VERTEX) return 35044;
	if (usage & Buffer.UNIFORM) return 35048;
	return 35044;
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/helpers/parse-shader-compiler-log.js
/**
* Parse a WebGL-format GLSL compilation log into an array of WebGPU style message records.
* This follows documented WebGL conventions for compilation logs.
* Based on https://github.com/wwwtyro/gl-format-compiler-error (public domain)
*/
function parseShaderCompilerLog(errLog) {
	const lines = errLog.split(/\r?\n/);
	const messages = [];
	for (const line of lines) {
		if (line.length <= 1) continue;
		const lineWithTrimmedWhitespace = line.trim();
		const segments = line.split(":");
		const trimmedMessageType = segments[0]?.trim();
		if (segments.length === 2) {
			const [messageType, message] = segments;
			if (!messageType || !message) {
				messages.push({
					message: lineWithTrimmedWhitespace,
					type: getMessageType(trimmedMessageType || "info"),
					lineNum: 0,
					linePos: 0
				});
				continue;
			}
			messages.push({
				message: message.trim(),
				type: getMessageType(messageType),
				lineNum: 0,
				linePos: 0
			});
			continue;
		}
		const [messageType, linePosition, lineNumber, ...rest] = segments;
		if (!messageType || !linePosition || !lineNumber) {
			messages.push({
				message: segments.slice(1).join(":").trim() || lineWithTrimmedWhitespace,
				type: getMessageType(trimmedMessageType || "info"),
				lineNum: 0,
				linePos: 0
			});
			continue;
		}
		let lineNum = parseInt(lineNumber, 10);
		if (Number.isNaN(lineNum)) lineNum = 0;
		let linePos = parseInt(linePosition, 10);
		if (Number.isNaN(linePos)) linePos = 0;
		messages.push({
			message: rest.join(":").trim(),
			type: getMessageType(messageType),
			lineNum,
			linePos
		});
	}
	return messages;
}
/** Ensure supported type */
function getMessageType(messageType) {
	const MESSAGE_TYPES = [
		"warning",
		"error",
		"info"
	];
	const lowerCaseType = messageType.toLowerCase();
	return MESSAGE_TYPES.includes(lowerCaseType) ? lowerCaseType : "info";
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/resources/webgl-shader.js
/**
* An immutable compiled shader program that execute portions of the GPU Pipeline
*/
var WEBGLShader = class extends Shader {
	device;
	handle;
	constructor(device, props) {
		super(device, props);
		this.device = device;
		switch (this.props.stage) {
			case "vertex":
				this.handle = this.props.handle || this.device.gl.createShader(35633);
				break;
			case "fragment":
				this.handle = this.props.handle || this.device.gl.createShader(35632);
				break;
			default: throw new Error(this.props.stage);
		}
		device._setWebGLDebugMetadata(this.handle, this, { spector: this.props });
		const compilationStatus = this._compile(this.source);
		if (compilationStatus && typeof compilationStatus.catch === "function") compilationStatus.catch(() => {
			this.compilationStatus = "error";
		});
	}
	destroy() {
		if (this.handle) {
			this.removeStats();
			this.device.gl.deleteShader(this.handle);
			this.destroyed = true;
			this.handle.destroyed = true;
		}
	}
	get asyncCompilationStatus() {
		return this._waitForCompilationComplete().then(() => {
			this._getCompilationStatus();
			return this.compilationStatus;
		});
	}
	async getCompilationInfo() {
		await this._waitForCompilationComplete();
		return this.getCompilationInfoSync();
	}
	getCompilationInfoSync() {
		const shaderLog = this.device.gl.getShaderInfoLog(this.handle);
		return shaderLog ? parseShaderCompilerLog(shaderLog) : [];
	}
	getTranslatedSource() {
		return this.device.getExtension("WEBGL_debug_shaders").WEBGL_debug_shaders?.getTranslatedShaderSource(this.handle) || null;
	}
	/** Compile a shader and get compilation status */
	_compile(source) {
		source = source.startsWith("#version ") ? source : `#version 300 es\n${source}`;
		const { gl } = this.device;
		gl.shaderSource(this.handle, source);
		gl.compileShader(this.handle);
		if (!this.device.props.debug) {
			this.compilationStatus = "pending";
			return;
		}
		if (!this.device.features.has("compilation-status-async-webgl")) {
			this._getCompilationStatus();
			this.debugShader();
			if (this.compilationStatus === "error") throw new Error(`GLSL compilation errors in ${this.props.stage} shader ${this.props.id}`);
			return;
		}
		log.once(1, "Shader compilation is asynchronous")();
		return this._waitForCompilationComplete().then(() => {
			log.info(2, `Shader ${this.id} - async compilation complete: ${this.compilationStatus}`)();
			this._getCompilationStatus();
			this.debugShader();
		});
	}
	/** Use KHR_parallel_shader_compile extension if available */
	async _waitForCompilationComplete() {
		const waitMs = async (ms) => await new Promise((resolve) => setTimeout(resolve, ms));
		const DELAY_MS = 10;
		if (!this.device.features.has("compilation-status-async-webgl")) {
			await waitMs(DELAY_MS);
			return;
		}
		const { gl } = this.device;
		for (;;) {
			if (gl.getShaderParameter(this.handle, 37297)) return;
			await waitMs(DELAY_MS);
		}
	}
	/**
	* Get the shader compilation status
	* TODO - Load log even when no error reported, to catch warnings?
	* https://gamedev.stackexchange.com/questions/30429/how-to-detect-glsl-warnings
	*/
	_getCompilationStatus() {
		this.compilationStatus = this.device.gl.getShaderParameter(this.handle, 35713) ? "success" : "error";
	}
};
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/converters/device-parameters.js
/**
* Execute a function with a set of temporary WebGL parameter overrides
* - Saves current "global" WebGL context settings
* - Sets the supplies WebGL context parameters,
* - Executes supplied function
* - Restores parameters
* - Returns the return value of the supplied function
*/
function withDeviceAndGLParameters(device, parameters, glParameters, func) {
	if (isObjectEmpty$1(parameters)) return func(device);
	const webglDevice = device;
	webglDevice.pushState();
	try {
		setDeviceParameters(device, parameters);
		setGLParameters(webglDevice.gl, glParameters);
		return func(device);
	} finally {
		webglDevice.popState();
	}
}
/** Set WebGPU Style Parameters */
function setDeviceParameters(device, parameters) {
	const webglDevice = device;
	const { gl } = webglDevice;
	if (parameters.cullMode) switch (parameters.cullMode) {
		case "none":
			gl.disable(2884);
			break;
		case "front":
			gl.enable(2884);
			gl.cullFace(1028);
			break;
		case "back":
			gl.enable(2884);
			gl.cullFace(1029);
			break;
	}
	if (parameters.frontFace) gl.frontFace(map("frontFace", parameters.frontFace, {
		ccw: 2305,
		cw: 2304
	}));
	if (parameters.unclippedDepth) {
		if (device.features.has("depth-clip-control")) gl.enable(34383);
	}
	if (parameters.depthBias !== void 0) {
		gl.enable(32823);
		gl.polygonOffset(parameters.depthBias, parameters.depthBiasSlopeScale || 0);
	}
	if (parameters.provokingVertex) {
		if (device.features.has("provoking-vertex-webgl")) {
			const ext = webglDevice.getExtension("WEBGL_provoking_vertex").WEBGL_provoking_vertex;
			const vertex = map("provokingVertex", parameters.provokingVertex, {
				first: 36429,
				last: 36430
			});
			ext?.provokingVertexWEBGL(vertex);
		}
	}
	if (parameters.polygonMode || parameters.polygonOffsetLine) {
		if (device.features.has("polygon-mode-webgl")) {
			if (parameters.polygonMode) {
				const ext = webglDevice.getExtension("WEBGL_polygon_mode").WEBGL_polygon_mode;
				const mode = map("polygonMode", parameters.polygonMode, {
					fill: 6914,
					line: 6913
				});
				ext?.polygonModeWEBGL(1028, mode);
				ext?.polygonModeWEBGL(1029, mode);
			}
			if (parameters.polygonOffsetLine) gl.enable(10754);
		}
	}
	if (device.features.has("shader-clip-cull-distance-webgl")) {
		if (parameters.clipDistance0) gl.enable(12288);
		if (parameters.clipDistance1) gl.enable(12289);
		if (parameters.clipDistance2) gl.enable(12290);
		if (parameters.clipDistance3) gl.enable(12291);
		if (parameters.clipDistance4) gl.enable(12292);
		if (parameters.clipDistance5) gl.enable(12293);
		if (parameters.clipDistance6) gl.enable(12294);
		if (parameters.clipDistance7) gl.enable(12295);
	}
	if (parameters.depthWriteEnabled !== void 0) gl.depthMask(mapBoolean("depthWriteEnabled", parameters.depthWriteEnabled));
	if (parameters.depthCompare) {
		parameters.depthCompare !== "always" ? gl.enable(2929) : gl.disable(2929);
		gl.depthFunc(convertCompareFunction("depthCompare", parameters.depthCompare));
	}
	if (parameters.clearDepth !== void 0) gl.clearDepth(parameters.clearDepth);
	if (parameters.stencilWriteMask) {
		const mask = parameters.stencilWriteMask;
		gl.stencilMaskSeparate(1028, mask);
		gl.stencilMaskSeparate(1029, mask);
	}
	if (parameters.stencilReadMask) log.warn("stencilReadMask not supported under WebGL");
	if (parameters.stencilCompare) {
		const mask = parameters.stencilReadMask || 4294967295;
		const glValue = convertCompareFunction("depthCompare", parameters.stencilCompare);
		parameters.stencilCompare !== "always" ? gl.enable(2960) : gl.disable(2960);
		gl.stencilFuncSeparate(1028, glValue, 0, mask);
		gl.stencilFuncSeparate(1029, glValue, 0, mask);
	}
	if (parameters.stencilPassOperation && parameters.stencilFailOperation && parameters.stencilDepthFailOperation) {
		const dppass = convertStencilOperation("stencilPassOperation", parameters.stencilPassOperation);
		const sfail = convertStencilOperation("stencilFailOperation", parameters.stencilFailOperation);
		const dpfail = convertStencilOperation("stencilDepthFailOperation", parameters.stencilDepthFailOperation);
		gl.stencilOpSeparate(1028, sfail, dpfail, dppass);
		gl.stencilOpSeparate(1029, sfail, dpfail, dppass);
	}
	switch (parameters.blend) {
		case true:
			gl.enable(3042);
			break;
		case false:
			gl.disable(3042);
			break;
		default:
	}
	if (parameters.blendColorOperation || parameters.blendAlphaOperation) {
		const colorEquation = convertBlendOperationToEquation("blendColorOperation", parameters.blendColorOperation || "add");
		const alphaEquation = convertBlendOperationToEquation("blendAlphaOperation", parameters.blendAlphaOperation || "add");
		gl.blendEquationSeparate(colorEquation, alphaEquation);
		const colorSrcFactor = convertBlendFactorToFunction("blendColorSrcFactor", parameters.blendColorSrcFactor || "one");
		const colorDstFactor = convertBlendFactorToFunction("blendColorDstFactor", parameters.blendColorDstFactor || "zero");
		const alphaSrcFactor = convertBlendFactorToFunction("blendAlphaSrcFactor", parameters.blendAlphaSrcFactor || "one");
		const alphaDstFactor = convertBlendFactorToFunction("blendAlphaDstFactor", parameters.blendAlphaDstFactor || "zero");
		gl.blendFuncSeparate(colorSrcFactor, colorDstFactor, alphaSrcFactor, alphaDstFactor);
	}
}
function convertCompareFunction(parameter, value) {
	return map(parameter, value, {
		never: 512,
		less: 513,
		equal: 514,
		"less-equal": 515,
		greater: 516,
		"not-equal": 517,
		"greater-equal": 518,
		always: 519
	});
}
function convertStencilOperation(parameter, value) {
	return map(parameter, value, {
		keep: 7680,
		zero: 0,
		replace: 7681,
		invert: 5386,
		"increment-clamp": 7682,
		"decrement-clamp": 7683,
		"increment-wrap": 34055,
		"decrement-wrap": 34056
	});
}
function convertBlendOperationToEquation(parameter, value) {
	return map(parameter, value, {
		add: 32774,
		subtract: 32778,
		"reverse-subtract": 32779,
		min: 32775,
		max: 32776
	});
}
function convertBlendFactorToFunction(parameter, value, type = "color") {
	return map(parameter, value, {
		one: 1,
		zero: 0,
		src: 768,
		"one-minus-src": 769,
		dst: 774,
		"one-minus-dst": 775,
		"src-alpha": 770,
		"one-minus-src-alpha": 771,
		"dst-alpha": 772,
		"one-minus-dst-alpha": 773,
		"src-alpha-saturated": 776,
		constant: type === "color" ? 32769 : 32771,
		"one-minus-constant": type === "color" ? 32770 : 32772,
		src1: 768,
		"one-minus-src1": 769,
		"src1-alpha": 770,
		"one-minus-src1-alpha": 771
	});
}
function message(parameter, value) {
	return `Illegal parameter ${value} for ${parameter}`;
}
function map(parameter, value, valueMap) {
	if (!(value in valueMap)) throw new Error(message(parameter, value));
	return valueMap[value];
}
function mapBoolean(parameter, value) {
	return value;
}
/** Returns true if given object is empty, false otherwise. */
function isObjectEmpty$1(obj) {
	let isEmpty = true;
	for (const key in obj) {
		isEmpty = false;
		break;
	}
	return isEmpty;
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/converters/sampler-parameters.js
/**
* Convert WebGPU-style sampler props to WebGL
* @param props
* @returns
*/
function convertSamplerParametersToWebGL(props) {
	const params = {};
	if (props.addressModeU) params[10242] = convertAddressMode(props.addressModeU);
	if (props.addressModeV) params[10243] = convertAddressMode(props.addressModeV);
	if (props.addressModeW) params[32882] = convertAddressMode(props.addressModeW);
	if (props.magFilter) params[10240] = convertMaxFilterMode(props.magFilter);
	if (props.minFilter || props.mipmapFilter) params[10241] = convertMinFilterMode(props.minFilter || "linear", props.mipmapFilter);
	if (props.lodMinClamp !== void 0) params[33082] = props.lodMinClamp;
	if (props.lodMaxClamp !== void 0) params[33083] = props.lodMaxClamp;
	if (props.type === "comparison-sampler") params[34892] = 34894;
	if (props.compare) params[34893] = convertCompareFunction("compare", props.compare);
	if (props.maxAnisotropy) params[34046] = props.maxAnisotropy;
	return params;
}
/** Convert address more */
function convertAddressMode(addressMode) {
	switch (addressMode) {
		case "clamp-to-edge": return 33071;
		case "repeat": return 10497;
		case "mirror-repeat": return 33648;
	}
}
function convertMaxFilterMode(maxFilter) {
	switch (maxFilter) {
		case "nearest": return 9728;
		case "linear": return 9729;
	}
}
/**
* WebGPU has separate min filter and mipmap filter,
* WebGL is combined and effectively offers 6 options
*/
function convertMinFilterMode(minFilter, mipmapFilter = "none") {
	if (!mipmapFilter) return convertMaxFilterMode(minFilter);
	switch (mipmapFilter) {
		case "none": return convertMaxFilterMode(minFilter);
		case "nearest":
			switch (minFilter) {
				case "nearest": return 9984;
				case "linear": return 9985;
			}
			break;
		case "linear": switch (minFilter) {
			case "nearest": return 9986;
			case "linear": return 9987;
		}
	}
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/resources/webgl-sampler.js
/**
* Sampler object -
* so that they can be set directly on the texture
* https://github.com/WebGLSamples/WebGL2Samples/blob/master/samples/sampler_object.html
*/
var WEBGLSampler = class extends Sampler {
	device;
	handle;
	parameters;
	constructor(device, props) {
		super(device, props);
		this.device = device;
		this.parameters = convertSamplerParametersToWebGL(props);
		this.handle = props.handle || this.device.gl.createSampler();
		this._setSamplerParameters(this.parameters);
	}
	destroy() {
		if (this.handle) {
			this.device.gl.deleteSampler(this.handle);
			this.handle = void 0;
		}
	}
	toString() {
		return `Sampler(${this.id},${JSON.stringify(this.props)})`;
	}
	/** Set sampler parameters on the sampler */
	_setSamplerParameters(parameters) {
		for (const [pname, value] of Object.entries(parameters)) {
			const param = Number(pname);
			switch (param) {
				case 33082:
				case 33083:
					this.device.gl.samplerParameterf(this.handle, param, value);
					break;
				default:
					this.device.gl.samplerParameteri(this.handle, param, value);
					break;
			}
		}
	}
};
//#endregion
//#region node_modules/@luma.gl/webgl/dist/context/state-tracker/with-parameters.js
/**
* Execute a function with a set of temporary WebGL parameter overrides
* - Saves current "global" WebGL context settings
* - Sets the supplies WebGL context parameters,
* - Executes supplied function
* - Restores parameters
* - Returns the return value of the supplied function
*/
function withGLParameters(gl, parameters, func) {
	if (isObjectEmpty(parameters)) return func(gl);
	const { nocatch = true } = parameters;
	const webglState = WebGLStateTracker.get(gl);
	webglState.push();
	setGLParameters(gl, parameters);
	let value;
	if (nocatch) {
		value = func(gl);
		webglState.pop();
	} else try {
		value = func(gl);
	} finally {
		webglState.pop();
	}
	return value;
}
function isObjectEmpty(object) {
	for (const key in object) return false;
	return true;
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/resources/webgl-texture-view.js
var WEBGLTextureView = class extends TextureView {
	device;
	gl;
	handle;
	texture;
	constructor(device, props) {
		super(device, {
			...Texture.defaultProps,
			...props
		});
		this.device = device;
		this.gl = this.device.gl;
		this.handle = null;
		this.texture = props.texture;
	}
};
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/converters/shader-formats.js
/** Get shadertypes data type from GL constants */
function convertGLDataTypeToDataType(type) {
	return GL_DATA_TYPE_MAP[type];
}
var GL_DATA_TYPE_MAP = {
	[5124]: "sint32",
	[5125]: "uint32",
	[5122]: "sint16",
	[5123]: "uint16",
	[5120]: "sint8",
	[5121]: "uint8",
	[5126]: "float32",
	[5131]: "float16",
	[33635]: "uint16",
	[32819]: "uint16",
	[32820]: "uint16",
	[33640]: "uint32",
	[35899]: "uint32",
	[35902]: "uint32",
	[34042]: "uint32",
	[36269]: "uint32"
};
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/resources/webgl-texture.js
/**
* WebGL... the texture API from hell... hopefully made simpler
*/
var WEBGLTexture = class extends Texture {
	device;
	gl;
	handle;
	sampler = void 0;
	view;
	/**
	* The WebGL target corresponding to the texture type
	* @note `target` cannot be modified by bind:
	* textures are special because when you first bind them to a target,
	* When you first bind a texture as a GL_TEXTURE_2D, you are saying that this texture is a 2D texture.
	* And it will always be a 2D texture; this state cannot be changed ever.
	* A texture that was first bound as a GL_TEXTURE_2D, must always be bound as a GL_TEXTURE_2D;
	* attempting to bind it as GL_TEXTURE_3D will give rise to a run-time error
	*/
	glTarget;
	/** The WebGL format - essentially channel structure */
	glFormat;
	/** The WebGL data format - the type of each channel */
	glType;
	/** The WebGL constant corresponding to the WebGPU style constant in format */
	glInternalFormat;
	/** Whether the internal format is compressed */
	compressed;
	/** Texture binding slot - TODO - move to texture view? */
	_textureUnit = 0;
	/** Cached framebuffer reused for color texture readback. */
	_framebuffer = null;
	/** Cache key for the currently attached readback subresource `${mipLevel}:${layer}`. */
	_framebufferAttachmentKey = null;
	constructor(device, props) {
		super(device, props, { byteAlignment: 1 });
		this.device = device;
		this.gl = this.device.gl;
		const formatInfo = getTextureFormatWebGL(this.props.format);
		this.glTarget = getWebGLTextureTarget(this.props.dimension);
		this.glInternalFormat = formatInfo.internalFormat;
		this.glFormat = formatInfo.format;
		this.glType = formatInfo.type;
		this.compressed = formatInfo.compressed;
		this.handle = this.props.handle || this.gl.createTexture();
		this.device._setWebGLDebugMetadata(this.handle, this, { spector: this.props });
		/**
		* Use WebGL immutable texture storage to allocate and clear texture memory.
		* - texStorage2D should be considered a preferred alternative to texImage2D. It may have lower memory costs than texImage2D in some implementations.
		* - Once texStorage*D has been called, the texture is immutable and can only be updated with texSubImage*(), not texImage()
		* @see https://registry.khronos.org/webgl/specs/latest/2.0/ WebGL 2 spec section 3.7.6
		*/
		this.gl.bindTexture(this.glTarget, this.handle);
		const { dimension, width, height, depth, mipLevels, glTarget, glInternalFormat } = this;
		if (!this.compressed) switch (dimension) {
			case "2d":
			case "cube":
				this.gl.texStorage2D(glTarget, mipLevels, glInternalFormat, width, height);
				break;
			case "2d-array":
			case "3d":
				this.gl.texStorage3D(glTarget, mipLevels, glInternalFormat, width, height, depth);
				break;
			default: throw new Error(dimension);
		}
		this.gl.bindTexture(this.glTarget, null);
		this._initializeData(props.data);
		if (!this.props.handle) this.trackAllocatedMemory(this.getAllocatedByteLength(), "Texture");
		else this.trackReferencedMemory(this.getAllocatedByteLength(), "Texture");
		this.setSampler(this.props.sampler);
		this.view = new WEBGLTextureView(this.device, {
			...this.props,
			texture: this
		});
		Object.seal(this);
	}
	destroy() {
		if (this.handle) {
			this._framebuffer?.destroy();
			this._framebuffer = null;
			this._framebufferAttachmentKey = null;
			this.removeStats();
			if (!this.props.handle) {
				this.gl.deleteTexture(this.handle);
				this.trackDeallocatedMemory("Texture");
			} else this.trackDeallocatedReferencedMemory("Texture");
			this.destroyed = true;
		}
	}
	createView(props) {
		return new WEBGLTextureView(this.device, {
			...props,
			texture: this
		});
	}
	setSampler(sampler = {}) {
		super.setSampler(sampler);
		const parameters = convertSamplerParametersToWebGL(this.sampler.props);
		this._setSamplerParameters(parameters);
	}
	copyExternalImage(options_) {
		const options = this._normalizeCopyExternalImageOptions(options_);
		if (options.sourceX || options.sourceY) throw new Error("WebGL does not support sourceX/sourceY)");
		const { glFormat, glType } = this;
		const { image, depth, mipLevel, x, y, z, width, height } = options;
		const glTarget = getWebGLCubeFaceTarget(this.glTarget, this.dimension, z);
		const glParameters = options.flipY ? { [37440]: true } : {};
		this.gl.bindTexture(this.glTarget, this.handle);
		withGLParameters(this.gl, glParameters, () => {
			switch (this.dimension) {
				case "2d":
				case "cube":
					this.gl.texSubImage2D(glTarget, mipLevel, x, y, width, height, glFormat, glType, image);
					break;
				case "2d-array":
				case "3d":
					this.gl.texSubImage3D(glTarget, mipLevel, x, y, z, width, height, depth, glFormat, glType, image);
					break;
				default:
			}
		});
		this.gl.bindTexture(this.glTarget, null);
		return {
			width: options.width,
			height: options.height
		};
	}
	copyImageData(options_) {
		super.copyImageData(options_);
	}
	/**
	* Reads a color texture subresource into a GPU buffer using `PIXEL_PACK_BUFFER`.
	*
	* @note Only first-pass color readback is supported. Unsupported formats and aspects throw
	* before any WebGL calls are issued.
	*/
	readBuffer(options = {}, buffer) {
		if (!buffer) throw new Error(`${this} readBuffer requires a destination buffer`);
		const normalizedOptions = this._getSupportedColorReadOptions(options);
		const byteOffset = options.byteOffset ?? 0;
		const memoryLayout = this.computeMemoryLayout(normalizedOptions);
		if (buffer.byteLength < byteOffset + memoryLayout.byteLength) throw new Error(`${this} readBuffer target is too small (${buffer.byteLength} < ${byteOffset + memoryLayout.byteLength})`);
		const webglBuffer = buffer;
		this.gl.bindBuffer(35051, webglBuffer.handle);
		try {
			this._readColorTextureLayers(normalizedOptions, memoryLayout, (destinationByteOffset) => {
				this.gl.readPixels(normalizedOptions.x, normalizedOptions.y, normalizedOptions.width, normalizedOptions.height, this.glFormat, this.glType, byteOffset + destinationByteOffset);
			});
		} finally {
			this.gl.bindBuffer(35051, null);
		}
		return buffer;
	}
	async readDataAsync(options = {}) {
		throw new Error(`${this} readDataAsync is deprecated; use readBuffer() with an explicit destination buffer or DynamicTexture.readAsync()`);
	}
	writeBuffer(buffer, options_ = {}) {
		const options = this._normalizeTextureWriteOptions(options_);
		const { width, height, depthOrArrayLayers, mipLevel, byteOffset, x, y, z } = options;
		const { glFormat, glType, compressed } = this;
		const glTarget = getWebGLCubeFaceTarget(this.glTarget, this.dimension, z);
		if (compressed) throw new Error("writeBuffer for compressed textures is not implemented in WebGL");
		const { bytesPerPixel } = this.device.getTextureFormatInfo(this.format);
		const unpackRowLength = bytesPerPixel ? options.bytesPerRow / bytesPerPixel : void 0;
		const glParameters = {
			[3317]: this.byteAlignment,
			...unpackRowLength !== void 0 ? { [3314]: unpackRowLength } : {},
			[32878]: options.rowsPerImage
		};
		this.gl.bindTexture(this.glTarget, this.handle);
		this.gl.bindBuffer(35052, buffer.handle);
		withGLParameters(this.gl, glParameters, () => {
			switch (this.dimension) {
				case "2d":
				case "cube":
					this.gl.texSubImage2D(glTarget, mipLevel, x, y, width, height, glFormat, glType, byteOffset);
					break;
				case "2d-array":
				case "3d":
					this.gl.texSubImage3D(glTarget, mipLevel, x, y, z, width, height, depthOrArrayLayers, glFormat, glType, byteOffset);
					break;
				default:
			}
		});
		this.gl.bindBuffer(35052, null);
		this.gl.bindTexture(this.glTarget, null);
	}
	writeData(data, options_ = {}) {
		const options = this._normalizeTextureWriteOptions(options_);
		const typedArray = ArrayBuffer.isView(data) ? data : new Uint8Array(data);
		const { width, height, depthOrArrayLayers, mipLevel, x, y, z, byteOffset } = options;
		const { glFormat, glType, compressed } = this;
		const glTarget = getWebGLCubeFaceTarget(this.glTarget, this.dimension, z);
		let unpackRowLength;
		if (!compressed) {
			const { bytesPerPixel } = this.device.getTextureFormatInfo(this.format);
			if (bytesPerPixel) unpackRowLength = options.bytesPerRow / bytesPerPixel;
		}
		const glParameters = !this.compressed ? {
			[3317]: this.byteAlignment,
			...unpackRowLength !== void 0 ? { [3314]: unpackRowLength } : {},
			[32878]: options.rowsPerImage
		} : {};
		const sourceElementOffset = getWebGLTextureSourceElementOffset(typedArray, byteOffset);
		const compressedData = compressed ? getArrayBufferView(typedArray, byteOffset) : typedArray;
		const mipLevelSize = this._getMipLevelSize(mipLevel);
		const isFullMipUpload = x === 0 && y === 0 && z === 0 && width === mipLevelSize.width && height === mipLevelSize.height && depthOrArrayLayers === mipLevelSize.depthOrArrayLayers;
		this.gl.bindTexture(this.glTarget, this.handle);
		this.gl.bindBuffer(35052, null);
		withGLParameters(this.gl, glParameters, () => {
			switch (this.dimension) {
				case "2d":
				case "cube":
					if (compressed) if (isFullMipUpload) this.gl.compressedTexImage2D(glTarget, mipLevel, glFormat, width, height, 0, compressedData);
					else this.gl.compressedTexSubImage2D(glTarget, mipLevel, x, y, width, height, glFormat, compressedData);
					else this.gl.texSubImage2D(glTarget, mipLevel, x, y, width, height, glFormat, glType, typedArray, sourceElementOffset);
					break;
				case "2d-array":
				case "3d":
					if (compressed) if (isFullMipUpload) this.gl.compressedTexImage3D(glTarget, mipLevel, glFormat, width, height, depthOrArrayLayers, 0, compressedData);
					else this.gl.compressedTexSubImage3D(glTarget, mipLevel, x, y, z, width, height, depthOrArrayLayers, glFormat, compressedData);
					else this.gl.texSubImage3D(glTarget, mipLevel, x, y, z, width, height, depthOrArrayLayers, glFormat, glType, typedArray, sourceElementOffset);
					break;
				default:
			}
		});
		this.gl.bindTexture(this.glTarget, null);
	}
	/** @todo - for now we always use 1 for maximum compatibility, we can fine tune later */
	_getRowByteAlignment(format, width) {
		return 1;
	}
	/**
	* Wraps a given texture into a framebuffer object, that can be further used
	* to read data from the texture object.
	*/
	_getFramebuffer() {
		this._framebuffer ||= this.device.createFramebuffer({
			id: `framebuffer-for-${this.id}`,
			width: this.width,
			height: this.height,
			colorAttachments: [this]
		});
		return this._framebuffer;
	}
	readDataSyncWebGL(options_ = {}) {
		const options = this._getSupportedColorReadOptions(options_);
		const memoryLayout = this.computeMemoryLayout(options);
		const ArrayType = getTypedArrayConstructor(convertGLDataTypeToDataType(this.glType));
		const targetArray = new ArrayType(memoryLayout.byteLength / ArrayType.BYTES_PER_ELEMENT);
		this._readColorTextureLayers(options, memoryLayout, (destinationByteOffset) => {
			const layerView = new ArrayType(targetArray.buffer, targetArray.byteOffset + destinationByteOffset, memoryLayout.bytesPerImage / ArrayType.BYTES_PER_ELEMENT);
			this.gl.readPixels(options.x, options.y, options.width, options.height, this.glFormat, this.glType, layerView);
		});
		return targetArray.buffer;
	}
	/**
	* Iterates the requested mip/layer/slice range, reattaching the cached read framebuffer as
	* needed before delegating the actual `readPixels()` call to the supplied callback.
	*/
	_readColorTextureLayers(options, memoryLayout, readLayer) {
		const framebuffer = this._getFramebuffer();
		const packRowLength = memoryLayout.bytesPerRow / memoryLayout.bytesPerPixel;
		const glParameters = {
			[3333]: this.byteAlignment,
			...packRowLength !== options.width ? { [3330]: packRowLength } : {}
		};
		const prevReadBuffer = this.gl.getParameter(3074);
		const prevHandle = this.gl.bindFramebuffer(36160, framebuffer.handle);
		try {
			this.gl.readBuffer(36064);
			withGLParameters(this.gl, glParameters, () => {
				for (let layerIndex = 0; layerIndex < options.depthOrArrayLayers; layerIndex++) {
					this._attachReadSubresource(framebuffer, options.mipLevel, options.z + layerIndex);
					readLayer(layerIndex * memoryLayout.bytesPerImage);
				}
			});
		} finally {
			this.gl.bindFramebuffer(36160, prevHandle || null);
			this.gl.readBuffer(prevReadBuffer);
		}
	}
	/**
	* Attaches a single color subresource to the cached read framebuffer.
	*
	* @note Repeated attachments of the same `(mipLevel, layer)` tuple are skipped.
	*/
	_attachReadSubresource(framebuffer, mipLevel, layer) {
		const attachmentKey = `${mipLevel}:${layer}`;
		if (this._framebufferAttachmentKey === attachmentKey) return;
		switch (this.dimension) {
			case "2d":
				this.gl.framebufferTexture2D(36160, 36064, 3553, this.handle, mipLevel);
				break;
			case "cube":
				this.gl.framebufferTexture2D(36160, 36064, getWebGLCubeFaceTarget(this.glTarget, this.dimension, layer), this.handle, mipLevel);
				break;
			case "2d-array":
			case "3d":
				this.gl.framebufferTextureLayer(36160, 36064, this.handle, mipLevel, layer);
				break;
			default: throw new Error(`${this} color readback does not support ${this.dimension} textures`);
		}
		if (this.device.props.debug) {
			const status = Number(this.gl.checkFramebufferStatus(36160));
			if (status !== 36053) throw new Error(`${framebuffer} incomplete for ${this} readback (${status})`);
		}
		this._framebufferAttachmentKey = attachmentKey;
	}
	/**
	* @note - this is used by the DynamicTexture class to generate mipmaps on WebGL
	*/
	generateMipmapsWebGL(options) {
		if (!(this.device.isTextureFormatRenderable(this.props.format) && this.device.isTextureFormatFilterable(this.props.format))) {
			log.warn(`${this} is not renderable or filterable, may not be able to generate mipmaps`)();
			if (!options?.force) return;
		}
		try {
			this.gl.bindTexture(this.glTarget, this.handle);
			this.gl.generateMipmap(this.glTarget);
		} catch (error) {
			log.warn(`Error generating mipmap for ${this}: ${error.message}`)();
		} finally {
			this.gl.bindTexture(this.glTarget, null);
		}
	}
	/**
	* Sets sampler parameters on texture
	*/
	_setSamplerParameters(parameters) {
		log.log(2, `${this.id} sampler parameters`, this.device.getGLKeys(parameters))();
		this.gl.bindTexture(this.glTarget, this.handle);
		for (const [pname, pvalue] of Object.entries(parameters)) {
			const param = Number(pname);
			const value = pvalue;
			switch (param) {
				case 33082:
				case 33083:
					this.gl.texParameterf(this.glTarget, param, value);
					break;
				case 10240:
				case 10241:
					this.gl.texParameteri(this.glTarget, param, value);
					break;
				case 10242:
				case 10243:
				case 32882:
					this.gl.texParameteri(this.glTarget, param, value);
					break;
				case 34046:
					if (this.device.features.has("texture-filterable-anisotropic-webgl")) this.gl.texParameteri(this.glTarget, param, value);
					break;
				case 34892:
				case 34893:
					this.gl.texParameteri(this.glTarget, param, value);
					break;
			}
		}
		this.gl.bindTexture(this.glTarget, null);
	}
	_getActiveUnit() {
		return this.gl.getParameter(34016) - 33984;
	}
	_bind(_textureUnit) {
		const { gl } = this;
		if (_textureUnit !== void 0) {
			this._textureUnit = _textureUnit;
			gl.activeTexture(33984 + _textureUnit);
		}
		gl.bindTexture(this.glTarget, this.handle);
		return _textureUnit;
	}
	_unbind(_textureUnit) {
		const { gl } = this;
		if (_textureUnit !== void 0) {
			this._textureUnit = _textureUnit;
			gl.activeTexture(33984 + _textureUnit);
		}
		gl.bindTexture(this.glTarget, null);
		return _textureUnit;
	}
};
function getArrayBufferView(typedArray, byteOffset = 0) {
	if (!byteOffset) return typedArray;
	return new typedArray.constructor(typedArray.buffer, typedArray.byteOffset + byteOffset, (typedArray.byteLength - byteOffset) / typedArray.BYTES_PER_ELEMENT);
}
function getWebGLTextureSourceElementOffset(typedArray, byteOffset) {
	if (byteOffset % typedArray.BYTES_PER_ELEMENT !== 0) throw new Error(`Texture byteOffset ${byteOffset} must align to typed array element size ${typedArray.BYTES_PER_ELEMENT}`);
	return byteOffset / typedArray.BYTES_PER_ELEMENT;
}
/** Convert a WebGPU style texture constant to a WebGL style texture constant */
function getWebGLTextureTarget(dimension) {
	switch (dimension) {
		case "1d": break;
		case "2d": return 3553;
		case "3d": return 32879;
		case "cube": return 34067;
		case "2d-array": return 35866;
		case "cube-array": break;
	}
	throw new Error(dimension);
}
/**
* In WebGL, cube maps specify faces by overriding target instead of using the depth parameter.
* @note We still bind the texture using GL.TEXTURE_CUBE_MAP, but we need to use the face-specific target when setting mip levels.
* @returns glTarget unchanged, if dimension !== 'cube'.
*/
function getWebGLCubeFaceTarget(glTarget, dimension, level) {
	return dimension === "cube" ? 34069 + level : glTarget;
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/helpers/set-uniform.js
/** Set a raw uniform (without type conversion and caching) */
function setUniform(gl, location, type, value) {
	const gl2 = gl;
	let uniformValue = value;
	if (uniformValue === true) uniformValue = 1;
	if (uniformValue === false) uniformValue = 0;
	const arrayValue = typeof uniformValue === "number" ? [uniformValue] : uniformValue;
	switch (type) {
		case 35678:
		case 35680:
		case 35679:
		case 35682:
		case 36289:
		case 36292:
		case 36293:
		case 36298:
		case 36299:
		case 36300:
		case 36303:
		case 36306:
		case 36307:
		case 36308:
		case 36311:
			if (typeof value !== "number") throw new Error("samplers must be set to integers");
			return gl.uniform1i(location, value);
		case 5126: return gl.uniform1fv(location, arrayValue);
		case 35664: return gl.uniform2fv(location, arrayValue);
		case 35665: return gl.uniform3fv(location, arrayValue);
		case 35666: return gl.uniform4fv(location, arrayValue);
		case 5124: return gl.uniform1iv(location, arrayValue);
		case 35667: return gl.uniform2iv(location, arrayValue);
		case 35668: return gl.uniform3iv(location, arrayValue);
		case 35669: return gl.uniform4iv(location, arrayValue);
		case 35670: return gl.uniform1iv(location, arrayValue);
		case 35671: return gl.uniform2iv(location, arrayValue);
		case 35672: return gl.uniform3iv(location, arrayValue);
		case 35673: return gl.uniform4iv(location, arrayValue);
		case 5125: return gl2.uniform1uiv(location, arrayValue, 1);
		case 36294: return gl2.uniform2uiv(location, arrayValue, 2);
		case 36295: return gl2.uniform3uiv(location, arrayValue, 3);
		case 36296: return gl2.uniform4uiv(location, arrayValue, 4);
		case 35674: return gl.uniformMatrix2fv(location, false, arrayValue);
		case 35675: return gl.uniformMatrix3fv(location, false, arrayValue);
		case 35676: return gl.uniformMatrix4fv(location, false, arrayValue);
		case 35685: return gl2.uniformMatrix2x3fv(location, false, arrayValue);
		case 35686: return gl2.uniformMatrix2x4fv(location, false, arrayValue);
		case 35687: return gl2.uniformMatrix3x2fv(location, false, arrayValue);
		case 35688: return gl2.uniformMatrix3x4fv(location, false, arrayValue);
		case 35689: return gl2.uniformMatrix4x2fv(location, false, arrayValue);
		case 35690: return gl2.uniformMatrix4x3fv(location, false, arrayValue);
	}
	throw new Error("Illegal uniform");
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/helpers/webgl-topology-utils.js
/** Get the primitive type for draw */
function getGLDrawMode(topology) {
	switch (topology) {
		case "point-list": return 0;
		case "line-list": return 1;
		case "line-strip": return 3;
		case "triangle-list": return 4;
		case "triangle-strip": return 5;
		default: throw new Error(topology);
	}
}
/** Get the primitive type for transform feedback */
function getGLPrimitive(topology) {
	switch (topology) {
		case "point-list": return 0;
		case "line-list": return 1;
		case "line-strip": return 1;
		case "triangle-list": return 4;
		case "triangle-strip": return 4;
		default: throw new Error(topology);
	}
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/resources/webgl-render-pipeline.js
/** Creates a new render pipeline */
var WEBGLRenderPipeline = class extends RenderPipeline {
	/** The WebGL device that created this render pipeline */
	device;
	/** Handle to underlying WebGL program */
	handle;
	/** vertex shader */
	vs;
	/** fragment shader */
	fs;
	/** The layout extracted from shader by WebGL introspection APIs */
	introspectedLayout;
	/** Compatibility path for direct pipeline.setBindings() usage */
	bindings = {};
	/** Compatibility path for direct pipeline.uniforms usage */
	uniforms = {};
	/** WebGL varyings */
	varyings = null;
	_uniformCount = 0;
	_uniformSetters = {};
	get [Symbol.toStringTag]() {
		return "WEBGLRenderPipeline";
	}
	constructor(device, props) {
		super(device, props);
		this.device = device;
		const webglSharedRenderPipeline = this.sharedRenderPipeline || this.device._createSharedRenderPipelineWebGL(props);
		this.sharedRenderPipeline = webglSharedRenderPipeline;
		this.handle = webglSharedRenderPipeline.handle;
		this.vs = webglSharedRenderPipeline.vs;
		this.fs = webglSharedRenderPipeline.fs;
		this.linkStatus = webglSharedRenderPipeline.linkStatus;
		this.introspectedLayout = webglSharedRenderPipeline.introspectedLayout;
		this.device._setWebGLDebugMetadata(this.handle, this, { spector: { id: this.props.id } });
		this.shaderLayout = props.shaderLayout ? mergeShaderLayout(this.introspectedLayout, props.shaderLayout) : this.introspectedLayout;
	}
	destroy() {
		if (this.destroyed) return;
		if (this.sharedRenderPipeline && !this.props._sharedRenderPipeline) this.sharedRenderPipeline.destroy();
		this.destroyResource();
	}
	/**
	* Compatibility shim for code paths that still set bindings on the pipeline.
	* Shared-model draws pass bindings per draw and do not rely on this state.
	*/
	setBindings(bindings, options) {
		const flatBindings = flattenBindingsByGroup(normalizeBindingsByGroup(this.shaderLayout, bindings));
		for (const [name, value] of Object.entries(flatBindings)) {
			const binding = getShaderLayoutBindingByName(this.shaderLayout, name);
			if (!binding) {
				const validBindings = this.shaderLayout.bindings.map((binding_) => `"${binding_.name}"`).join(", ");
				if (!options?.disableWarnings) log.warn(`No binding "${name}" in render pipeline "${this.id}", expected one of ${validBindings}`, value)();
			} else {
				if (!value) log.warn(`Unsetting binding "${name}" in render pipeline "${this.id}"`)();
				switch (binding.type) {
					case "uniform":
						if (!(value instanceof WEBGLBuffer) && !(value.buffer instanceof WEBGLBuffer)) throw new Error("buffer value");
						break;
					case "texture":
						if (!(value instanceof WEBGLTextureView || value instanceof WEBGLTexture || value instanceof WEBGLFramebuffer)) throw new Error(`${this} Bad texture binding for ${name}`);
						break;
					case "sampler":
						log.warn(`Ignoring sampler ${name}`)();
						break;
					default: throw new Error(binding.type);
				}
				this.bindings[name] = value;
			}
		}
	}
	/** @todo needed for portable model
	* @note The WebGL API is offers many ways to draw things
	* This function unifies those ways into a single call using common parameters with sane defaults
	*/
	draw(options) {
		this._syncLinkStatus();
		const drawBindings = options.bindGroups ? flattenBindingsByGroup(options.bindGroups) : options.bindings || this.bindings;
		const { renderPass, parameters = this.props.parameters, topology = this.props.topology, vertexArray, vertexCount, instanceCount, isInstanced = false, firstVertex = 0, transformFeedback, uniforms = this.uniforms } = options;
		const glDrawMode = getGLDrawMode(topology);
		const isIndexed = Boolean(vertexArray.indexBuffer);
		const glIndexType = vertexArray.indexBuffer?.glIndexType;
		if (this.linkStatus !== "success") {
			log.info(2, `RenderPipeline:${this.id}.draw() aborted - waiting for shader linking`)();
			return false;
		}
		if (!this._areTexturesRenderable(drawBindings)) {
			log.info(2, `RenderPipeline:${this.id}.draw() aborted - textures not yet loaded`)();
			return false;
		}
		this.device.gl.useProgram(this.handle);
		vertexArray.bindBeforeRender(renderPass);
		if (transformFeedback) transformFeedback.begin(this.props.topology);
		this._applyBindings(drawBindings, { disableWarnings: this.props.disableWarnings });
		this._applyUniforms(uniforms);
		const webglRenderPass = renderPass;
		withDeviceAndGLParameters(this.device, parameters, webglRenderPass.glParameters, () => {
			if (isIndexed && isInstanced) this.device.gl.drawElementsInstanced(glDrawMode, vertexCount || 0, glIndexType, firstVertex, instanceCount || 0);
			else if (isIndexed) this.device.gl.drawElements(glDrawMode, vertexCount || 0, glIndexType, firstVertex);
			else if (isInstanced) this.device.gl.drawArraysInstanced(glDrawMode, firstVertex, vertexCount || 0, instanceCount || 0);
			else this.device.gl.drawArrays(glDrawMode, firstVertex, vertexCount || 0);
			if (transformFeedback) transformFeedback.end();
		});
		vertexArray.unbindAfterRender(renderPass);
		return true;
	}
	/**
	* Checks if all texture-values uniforms are renderable (i.e. loaded)
	* Update a texture if needed (e.g. from video)
	* Note: This is currently done before every draw call
	*/
	_areTexturesRenderable(bindings) {
		let texturesRenderable = true;
		for (const bindingInfo of this.shaderLayout.bindings) if (!getBindingValueForLayoutBinding(bindings, bindingInfo.name)) {
			log.warn(`Binding ${bindingInfo.name} not found in ${this.id}`)();
			texturesRenderable = false;
		}
		return texturesRenderable;
	}
	/** Apply any bindings (before each draw call) */
	_applyBindings(bindings, _options) {
		this._syncLinkStatus();
		if (this.linkStatus !== "success") return;
		const { gl } = this.device;
		gl.useProgram(this.handle);
		let textureUnit = 0;
		let uniformBufferIndex = 0;
		for (const binding of this.shaderLayout.bindings) {
			const value = getBindingValueForLayoutBinding(bindings, binding.name);
			if (!value) throw new Error(`No value for binding ${binding.name} in ${this.id}`);
			switch (binding.type) {
				case "uniform":
					const { name } = binding;
					const location = gl.getUniformBlockIndex(this.handle, name);
					if (location === 4294967295) throw new Error(`Invalid uniform block name ${name}`);
					gl.uniformBlockBinding(this.handle, location, uniformBufferIndex);
					if (value instanceof WEBGLBuffer) gl.bindBufferBase(35345, uniformBufferIndex, value.handle);
					else {
						const bufferBinding = value;
						gl.bindBufferRange(35345, uniformBufferIndex, bufferBinding.buffer.handle, bufferBinding.offset || 0, bufferBinding.size || bufferBinding.buffer.byteLength - (bufferBinding.offset || 0));
					}
					uniformBufferIndex += 1;
					break;
				case "texture":
					if (!(value instanceof WEBGLTextureView || value instanceof WEBGLTexture || value instanceof WEBGLFramebuffer)) throw new Error("texture");
					let texture;
					if (value instanceof WEBGLTextureView) texture = value.texture;
					else if (value instanceof WEBGLTexture) texture = value;
					else if (value instanceof WEBGLFramebuffer && value.colorAttachments[0] instanceof WEBGLTextureView) {
						log.warn("Passing framebuffer in texture binding may be deprecated. Use fbo.colorAttachments[0] instead")();
						texture = value.colorAttachments[0].texture;
					} else throw new Error("No texture");
					gl.activeTexture(33984 + textureUnit);
					gl.bindTexture(texture.glTarget, texture.handle);
					textureUnit += 1;
					break;
				case "sampler": break;
				case "storage":
				case "read-only-storage": throw new Error(`binding type '${binding.type}' not supported in WebGL`);
			}
		}
	}
	/**
	* Due to program sharing, uniforms need to be reset before every draw call
	* (though caching will avoid redundant WebGL calls)
	*/
	_applyUniforms(uniforms) {
		for (const uniformLayout of this.shaderLayout.uniforms || []) {
			const { name, location, type, textureUnit } = uniformLayout;
			const value = uniforms[name] ?? textureUnit;
			if (value !== void 0) setUniform(this.device.gl, location, type, value);
		}
	}
	_syncLinkStatus() {
		this.linkStatus = this.sharedRenderPipeline.linkStatus;
	}
};
/**
* Merges an provided shader layout into a base shader layout
* In WebGL, this allows the auto generated shader layout to be overridden by the application
* Typically to change the format of the vertex attributes (from float32x4 to uint8x4 etc).
* @todo Drop this? Aren't all use cases covered by mergeBufferLayout()?
*/
function mergeShaderLayout(baseLayout, overrideLayout) {
	const mergedLayout = {
		...baseLayout,
		attributes: baseLayout.attributes.map((attribute) => ({ ...attribute })),
		bindings: baseLayout.bindings.map((binding) => ({ ...binding }))
	};
	for (const attribute of overrideLayout?.attributes || []) {
		const baseAttribute = mergedLayout.attributes.find((attr) => attr.name === attribute.name);
		if (!baseAttribute) log.warn(`shader layout attribute ${attribute.name} not present in shader`);
		else {
			baseAttribute.type = attribute.type || baseAttribute.type;
			baseAttribute.stepMode = attribute.stepMode || baseAttribute.stepMode;
		}
	}
	for (const binding of overrideLayout?.bindings || []) {
		const baseBinding = getShaderLayoutBindingByName(mergedLayout, binding.name);
		if (!baseBinding) {
			log.warn(`shader layout binding ${binding.name} not present in shader`);
			continue;
		}
		Object.assign(baseBinding, binding);
	}
	return mergedLayout;
}
function getShaderLayoutBindingByName(shaderLayout, bindingName) {
	return shaderLayout.bindings.find((binding) => binding.name === bindingName || binding.name === `${bindingName}Uniforms` || `${binding.name}Uniforms` === bindingName);
}
function getBindingValueForLayoutBinding(bindings, bindingName) {
	return bindings[bindingName] || bindings[`${bindingName}Uniforms`] || bindings[bindingName.replace(/Uniforms$/, "")];
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/converters/webgl-shadertypes.js
/** Converts to a luma shadertype to a GL data type (GL.BYTE, GL.FLOAT32 etc)  */
function convertDataTypeToGLDataType(normalizedType) {
	return NORMALIZED_SHADER_TYPE_TO_WEBGL[normalizedType];
}
/** Convert a WebGL "compisite type (e.g. GL.VEC3) into the corresponding luma shader uniform type */
function convertGLUniformTypeToShaderVariableType(glUniformType) {
	return WEBGL_SHADER_TYPES[glUniformType];
}
/** Check if a WebGL "uniform:" is a texture binding */
function isGLSamplerType(type) {
	return Boolean(WEBGL_SAMPLER_TO_TEXTURE_BINDINGS[type]);
}
function getTextureBindingFromGLSamplerType(glSamplerType) {
	return WEBGL_SAMPLER_TO_TEXTURE_BINDINGS[glSamplerType];
}
var WEBGL_SHADER_TYPES = {
	[5126]: "f32",
	[35664]: "vec2<f32>",
	[35665]: "vec3<f32>",
	[35666]: "vec4<f32>",
	[5124]: "i32",
	[35667]: "vec2<i32>",
	[35668]: "vec3<i32>",
	[35669]: "vec4<i32>",
	[5125]: "u32",
	[36294]: "vec2<u32>",
	[36295]: "vec3<u32>",
	[36296]: "vec4<u32>",
	[35670]: "f32",
	[35671]: "vec2<f32>",
	[35672]: "vec3<f32>",
	[35673]: "vec4<f32>",
	[35674]: "mat2x2<f32>",
	[35685]: "mat2x3<f32>",
	[35686]: "mat2x4<f32>",
	[35687]: "mat3x2<f32>",
	[35675]: "mat3x3<f32>",
	[35688]: "mat3x4<f32>",
	[35689]: "mat4x2<f32>",
	[35690]: "mat4x3<f32>",
	[35676]: "mat4x4<f32>"
};
var WEBGL_SAMPLER_TO_TEXTURE_BINDINGS = {
	[35678]: {
		viewDimension: "2d",
		sampleType: "float"
	},
	[35680]: {
		viewDimension: "cube",
		sampleType: "float"
	},
	[35679]: {
		viewDimension: "3d",
		sampleType: "float"
	},
	[35682]: {
		viewDimension: "3d",
		sampleType: "depth"
	},
	[36289]: {
		viewDimension: "2d-array",
		sampleType: "float"
	},
	[36292]: {
		viewDimension: "2d-array",
		sampleType: "depth"
	},
	[36293]: {
		viewDimension: "cube",
		sampleType: "float"
	},
	[36298]: {
		viewDimension: "2d",
		sampleType: "sint"
	},
	[36299]: {
		viewDimension: "3d",
		sampleType: "sint"
	},
	[36300]: {
		viewDimension: "cube",
		sampleType: "sint"
	},
	[36303]: {
		viewDimension: "2d-array",
		sampleType: "uint"
	},
	[36306]: {
		viewDimension: "2d",
		sampleType: "uint"
	},
	[36307]: {
		viewDimension: "3d",
		sampleType: "uint"
	},
	[36308]: {
		viewDimension: "cube",
		sampleType: "uint"
	},
	[36311]: {
		viewDimension: "2d-array",
		sampleType: "uint"
	}
};
/** Map from WebGL normalized types to WebGL */
var NORMALIZED_SHADER_TYPE_TO_WEBGL = {
	uint8: 5121,
	sint8: 5120,
	unorm8: 5121,
	snorm8: 5120,
	uint16: 5123,
	sint16: 5122,
	unorm16: 5123,
	snorm16: 5122,
	uint32: 5125,
	sint32: 5124,
	float16: 5131,
	float32: 5126
};
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/helpers/get-shader-layout-from-glsl.js
/**
* Extract metadata describing binding information for a program's shaders
* Note: `linkProgram()` needs to have been called
* (although linking does not need to have been successful).
*/
function getShaderLayoutFromGLSL(gl, program) {
	const shaderLayout = {
		attributes: [],
		bindings: []
	};
	shaderLayout.attributes = readAttributeDeclarations(gl, program);
	const uniformBlocks = readUniformBlocks(gl, program);
	for (const uniformBlock of uniformBlocks) {
		const uniforms = uniformBlock.uniforms.map((uniform) => ({
			name: uniform.name,
			format: uniform.format,
			byteOffset: uniform.byteOffset,
			byteStride: uniform.byteStride,
			arrayLength: uniform.arrayLength
		}));
		shaderLayout.bindings.push({
			type: "uniform",
			name: uniformBlock.name,
			group: 0,
			location: uniformBlock.location,
			visibility: (uniformBlock.vertex ? 1 : 0) & (uniformBlock.fragment ? 2 : 0),
			minBindingSize: uniformBlock.byteLength,
			uniforms
		});
	}
	const uniforms = readUniformBindings(gl, program);
	let textureUnit = 0;
	for (const uniform of uniforms) if (isGLSamplerType(uniform.type)) {
		const { viewDimension, sampleType } = getTextureBindingFromGLSamplerType(uniform.type);
		shaderLayout.bindings.push({
			type: "texture",
			name: uniform.name,
			group: 0,
			location: textureUnit,
			viewDimension,
			sampleType
		});
		uniform.textureUnit = textureUnit;
		textureUnit += 1;
	}
	if (uniforms.length) shaderLayout.uniforms = uniforms;
	const varyings = readVaryings(gl, program);
	if (varyings?.length) shaderLayout.varyings = varyings;
	return shaderLayout;
}
/**
* Extract info about all transform feedback varyings
*
* linkProgram needs to have been called, although linking does not need to have been successful
*/
function readAttributeDeclarations(gl, program) {
	const attributes = [];
	const count = gl.getProgramParameter(program, 35721);
	for (let index = 0; index < count; index++) {
		const activeInfo = gl.getActiveAttrib(program, index);
		if (!activeInfo) throw new Error("activeInfo");
		const { name, type: compositeType } = activeInfo;
		const location = gl.getAttribLocation(program, name);
		if (location >= 0) {
			const attributeType = convertGLUniformTypeToShaderVariableType(compositeType);
			const stepMode = /instance/i.test(name) ? "instance" : "vertex";
			attributes.push({
				name,
				location,
				stepMode,
				type: attributeType
			});
		}
	}
	attributes.sort((a, b) => a.location - b.location);
	return attributes;
}
/**
* Extract info about all transform feedback varyings
*
* linkProgram needs to have been called, although linking does not need to have been successful
*/
function readVaryings(gl, program) {
	const varyings = [];
	const count = gl.getProgramParameter(program, 35971);
	for (let location = 0; location < count; location++) {
		const activeInfo = gl.getTransformFeedbackVarying(program, location);
		if (!activeInfo) throw new Error("activeInfo");
		const { name, type: glUniformType, size } = activeInfo;
		const { type, components } = getVariableShaderTypeInfo(convertGLUniformTypeToShaderVariableType(glUniformType));
		varyings.push({
			location,
			name,
			type,
			size: size * components
		});
	}
	varyings.sort((a, b) => a.location - b.location);
	return varyings;
}
/**
* Extract info about all uniforms
*
* Query uniform locations and build name to setter map.
*/
function readUniformBindings(gl, program) {
	const uniforms = [];
	const uniformCount = gl.getProgramParameter(program, 35718);
	for (let i = 0; i < uniformCount; i++) {
		const activeInfo = gl.getActiveUniform(program, i);
		if (!activeInfo) throw new Error("activeInfo");
		const { name: rawName, size, type } = activeInfo;
		const { name, isArray } = parseUniformName(rawName);
		let webglLocation = gl.getUniformLocation(program, name);
		const uniformInfo = {
			location: webglLocation,
			name,
			size,
			type,
			isArray
		};
		uniforms.push(uniformInfo);
		if (uniformInfo.size > 1) for (let j = 0; j < uniformInfo.size; j++) {
			const elementName = `${name}[${j}]`;
			webglLocation = gl.getUniformLocation(program, elementName);
			const arrayElementUniformInfo = {
				...uniformInfo,
				name: elementName,
				location: webglLocation
			};
			uniforms.push(arrayElementUniformInfo);
		}
	}
	return uniforms;
}
/**
* Extract info about all "active" uniform blocks
* @note In WebGL, "active" just means that unused (inactive) blocks may have been optimized away during linking)
*/
function readUniformBlocks(gl, program) {
	const getBlockParameter = (blockIndex, pname) => gl.getActiveUniformBlockParameter(program, blockIndex, pname);
	const uniformBlocks = [];
	const blockCount = gl.getProgramParameter(program, 35382);
	for (let blockIndex = 0; blockIndex < blockCount; blockIndex++) {
		const blockInfo = {
			name: gl.getActiveUniformBlockName(program, blockIndex) || "",
			location: getBlockParameter(blockIndex, 35391),
			byteLength: getBlockParameter(blockIndex, 35392),
			vertex: getBlockParameter(blockIndex, 35396),
			fragment: getBlockParameter(blockIndex, 35398),
			uniformCount: getBlockParameter(blockIndex, 35394),
			uniforms: []
		};
		const uniformIndices = getBlockParameter(blockIndex, 35395) || [];
		const uniformType = gl.getActiveUniforms(program, uniformIndices, 35383);
		const uniformArrayLength = gl.getActiveUniforms(program, uniformIndices, 35384);
		const uniformOffset = gl.getActiveUniforms(program, uniformIndices, 35387);
		const uniformStride = gl.getActiveUniforms(program, uniformIndices, 35388);
		for (let i = 0; i < blockInfo.uniformCount; ++i) {
			const uniformIndex = uniformIndices[i];
			if (uniformIndex !== void 0) {
				const activeInfo = gl.getActiveUniform(program, uniformIndex);
				if (!activeInfo) throw new Error("activeInfo");
				const format = convertGLUniformTypeToShaderVariableType(uniformType[i]);
				blockInfo.uniforms.push({
					name: activeInfo.name,
					format,
					type: uniformType[i],
					arrayLength: uniformArrayLength[i],
					byteOffset: uniformOffset[i],
					byteStride: uniformStride[i]
				});
			}
		}
		const uniformInstancePrefixes = new Set(blockInfo.uniforms.map((uniform) => uniform.name.split(".")[0]).filter((instanceName) => Boolean(instanceName)));
		const blockAlias = blockInfo.name.replace(/Uniforms$/, "");
		if (uniformInstancePrefixes.size === 1 && !uniformInstancePrefixes.has(blockInfo.name) && !uniformInstancePrefixes.has(blockAlias)) {
			const [instanceName] = uniformInstancePrefixes;
			log.warn(`Uniform block "${blockInfo.name}" uses GLSL instance "${instanceName}". luma.gl binds uniform buffers by block name ("${blockInfo.name}") and alias ("${blockAlias}"). Prefer matching the instance name to one of those to avoid confusing silent mismatches.`)();
		}
		uniformBlocks.push(blockInfo);
	}
	uniformBlocks.sort((a, b) => a.location - b.location);
	return uniformBlocks;
}
/**
* TOOD - compare with a above, confirm copy, then delete
const bindings: Binding[] = [];
const count = gl.getProgramParameter(program, gl.ACTIVE_UNIFORM_BLOCKS);
for (let blockIndex = 0; blockIndex < count; blockIndex++) {
const vertex = gl.getActiveUniformBlockParameter(program, blockIndex, gl.UNIFORM_BLOCK_REFERENCED_BY_VERTEX_SHADER),
const fragment = gl.getActiveUniformBlockParameter(program, blockIndex, gl.UNIFORM_BLOCK_REFERENCED_BY_FRAGMENT_SHADER),
const visibility = (vertex) + (fragment);
const binding: BufferBinding = {
location: gl.getActiveUniformBlockParameter(program, blockIndex, gl.UNIFORM_BLOCK_BINDING),
// name: gl.getActiveUniformBlockName(program, blockIndex),
type: 'uniform',
visibility,
minBindingSize: gl.getActiveUniformBlockParameter(program, blockIndex, gl.UNIFORM_BLOCK_DATA_SIZE),
// uniformCount: gl.getActiveUniformBlockParameter(program, blockIndex, gl.UNIFORM_BLOCK_ACTIVE_UNIFORMS),
// uniformIndices: gl.getActiveUniformBlockParameter(program, blockIndex, gl.UNIFORM_BLOCK_ACTIVE_UNIFORM_INDICES),
}
bindings.push(binding);
}
*/
function parseUniformName(name) {
	if (name[name.length - 1] !== "]") return {
		name,
		length: 1,
		isArray: false
	};
	const matches = /([^[]*)(\[[0-9]+\])?/.exec(name);
	return {
		name: assertDefined(matches?.[1], `Failed to parse GLSL uniform name ${name}`),
		length: matches?.[2] ? 1 : 0,
		isArray: Boolean(matches?.[2])
	};
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/resources/webgl-shared-render-pipeline.js
var LOG_PROGRAM_PERF_PRIORITY = 4;
var WEBGLSharedRenderPipeline = class extends SharedRenderPipeline {
	device;
	handle;
	vs;
	fs;
	introspectedLayout = {
		attributes: [],
		bindings: [],
		uniforms: []
	};
	linkStatus = "pending";
	constructor(device, props) {
		super(device, props);
		this.device = device;
		this.handle = props.handle || this.device.gl.createProgram();
		this.vs = props.vs;
		this.fs = props.fs;
		if (props.varyings && props.varyings.length > 0) this.device.gl.transformFeedbackVaryings(this.handle, props.varyings, props.bufferMode || 35981);
		this._linkShaders();
		log.time(3, `RenderPipeline ${this.id} - shaderLayout introspection`)();
		this.introspectedLayout = getShaderLayoutFromGLSL(this.device.gl, this.handle);
		log.timeEnd(3, `RenderPipeline ${this.id} - shaderLayout introspection`)();
	}
	destroy() {
		if (this.destroyed) return;
		this.device.gl.useProgram(null);
		this.device.gl.deleteProgram(this.handle);
		this.handle.destroyed = true;
		this.destroyResource();
	}
	async _linkShaders() {
		const { gl } = this.device;
		gl.attachShader(this.handle, this.vs.handle);
		gl.attachShader(this.handle, this.fs.handle);
		log.time(LOG_PROGRAM_PERF_PRIORITY, `linkProgram for ${this.id}`)();
		gl.linkProgram(this.handle);
		log.timeEnd(LOG_PROGRAM_PERF_PRIORITY, `linkProgram for ${this.id}`)();
		if (!this.device.features.has("compilation-status-async-webgl")) {
			const status = this._getLinkStatus();
			this._reportLinkStatus(status);
			return;
		}
		log.once(1, "RenderPipeline linking is asynchronous")();
		await this._waitForLinkComplete();
		log.info(2, `RenderPipeline ${this.id} - async linking complete: ${this.linkStatus}`)();
		const status = this._getLinkStatus();
		this._reportLinkStatus(status);
	}
	async _reportLinkStatus(status) {
		switch (status) {
			case "success": return;
			default:
				const errorType = status === "link-error" ? "Link error" : "Validation error";
				switch (this.vs.compilationStatus) {
					case "error":
						this.vs.debugShader();
						throw new Error(`${this} ${errorType} during compilation of ${this.vs}`);
					case "pending":
						await this.vs.asyncCompilationStatus;
						this.vs.debugShader();
						break;
					case "success": break;
				}
				switch (this.fs?.compilationStatus) {
					case "error":
						this.fs.debugShader();
						throw new Error(`${this} ${errorType} during compilation of ${this.fs}`);
					case "pending":
						await this.fs.asyncCompilationStatus;
						this.fs.debugShader();
						break;
					case "success": break;
				}
				const linkErrorLog = this.device.gl.getProgramInfoLog(this.handle);
				this.device.reportError(/* @__PURE__ */ new Error(`${errorType} during ${status}: ${linkErrorLog}`), this)();
				this.device.debug();
		}
	}
	_getLinkStatus() {
		const { gl } = this.device;
		if (!gl.getProgramParameter(this.handle, 35714)) {
			this.linkStatus = "error";
			return "link-error";
		}
		this._initializeSamplerUniforms();
		gl.validateProgram(this.handle);
		if (!gl.getProgramParameter(this.handle, 35715)) {
			this.linkStatus = "error";
			return "validation-error";
		}
		this.linkStatus = "success";
		return "success";
	}
	_initializeSamplerUniforms() {
		const { gl } = this.device;
		gl.useProgram(this.handle);
		let textureUnit = 0;
		const uniformCount = gl.getProgramParameter(this.handle, 35718);
		for (let uniformIndex = 0; uniformIndex < uniformCount; uniformIndex++) {
			const activeInfo = gl.getActiveUniform(this.handle, uniformIndex);
			if (activeInfo && isGLSamplerType(activeInfo.type)) {
				const isArray = activeInfo.name.endsWith("[0]");
				const uniformName = isArray ? activeInfo.name.slice(0, -3) : activeInfo.name;
				const location = gl.getUniformLocation(this.handle, uniformName);
				if (location !== null) textureUnit = this._assignSamplerUniform(location, activeInfo, isArray, textureUnit);
			}
		}
	}
	_assignSamplerUniform(location, activeInfo, isArray, textureUnit) {
		const { gl } = this.device;
		if (isArray && activeInfo.size > 1) {
			const textureUnits = Int32Array.from({ length: activeInfo.size }, (_, arrayIndex) => textureUnit + arrayIndex);
			gl.uniform1iv(location, textureUnits);
			return textureUnit + activeInfo.size;
		}
		gl.uniform1i(location, textureUnit);
		return textureUnit + 1;
	}
	async _waitForLinkComplete() {
		const waitMs = async (ms) => await new Promise((resolve) => setTimeout(resolve, ms));
		const DELAY_MS = 10;
		if (!this.device.features.has("compilation-status-async-webgl")) {
			await waitMs(DELAY_MS);
			return;
		}
		const { gl } = this.device;
		for (;;) {
			if (gl.getProgramParameter(this.handle, 37297)) return;
			await waitMs(DELAY_MS);
		}
	}
};
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/resources/webgl-command-buffer.js
var WEBGLCommandBuffer = class extends CommandBuffer {
	device;
	handle = null;
	commands = [];
	constructor(device, props = {}) {
		super(device, props);
		this.device = device;
	}
	_executeCommands(commands = this.commands) {
		for (const command of commands) switch (command.name) {
			case "copy-buffer-to-buffer":
				_copyBufferToBuffer(this.device, command.options);
				break;
			case "copy-buffer-to-texture":
				_copyBufferToTexture(this.device, command.options);
				break;
			case "copy-texture-to-buffer":
				_copyTextureToBuffer(this.device, command.options);
				break;
			case "copy-texture-to-texture":
				_copyTextureToTexture(this.device, command.options);
				break;
			default: throw new Error(command.name);
		}
	}
};
function _copyBufferToBuffer(device, options) {
	const source = options.sourceBuffer;
	const destination = options.destinationBuffer;
	device.gl.bindBuffer(36662, source.handle);
	device.gl.bindBuffer(36663, destination.handle);
	device.gl.copyBufferSubData(36662, 36663, options.sourceOffset ?? 0, options.destinationOffset ?? 0, options.size);
	device.gl.bindBuffer(36662, null);
	device.gl.bindBuffer(36663, null);
}
/**
* Copies data from a Buffer object into a Texture object
* NOTE: doesn't wait for copy to be complete
*/
function _copyBufferToTexture(_device, _options) {
	throw new Error("copyBufferToTexture is not supported in WebGL");
}
/**
* Copies data from a Texture object into a Buffer object.
* NOTE: doesn't wait for copy to be complete
*/
function _copyTextureToBuffer(device, options) {
	const { sourceTexture, mipLevel = 0, aspect = "all", width = options.sourceTexture.width, height = options.sourceTexture.height, depthOrArrayLayers, origin = [
		0,
		0,
		0
	], destinationBuffer, byteOffset = 0, bytesPerRow, rowsPerImage } = options;
	if (sourceTexture instanceof Texture) {
		sourceTexture.readBuffer({
			x: origin[0] ?? 0,
			y: origin[1] ?? 0,
			z: origin[2] ?? 0,
			width,
			height,
			depthOrArrayLayers,
			mipLevel,
			aspect,
			byteOffset
		}, destinationBuffer);
		return;
	}
	if (aspect !== "all") throw new Error("aspect not supported in WebGL");
	if (mipLevel !== 0 || depthOrArrayLayers !== void 0 || bytesPerRow || rowsPerImage) throw new Error("not implemented");
	const { framebuffer, destroyFramebuffer } = getFramebuffer$1(sourceTexture);
	let prevHandle;
	try {
		const webglBuffer = destinationBuffer;
		const sourceWidth = width || framebuffer.width;
		const sourceHeight = height || framebuffer.height;
		const sourceParams = getTextureFormatWebGL(assertDefined(framebuffer.colorAttachments[0]).texture.props.format);
		const sourceFormat = sourceParams.format;
		const sourceType = sourceParams.type;
		device.gl.bindBuffer(35051, webglBuffer.handle);
		prevHandle = device.gl.bindFramebuffer(36160, framebuffer.handle);
		device.gl.readPixels(origin[0], origin[1], sourceWidth, sourceHeight, sourceFormat, sourceType, byteOffset);
	} finally {
		device.gl.bindBuffer(35051, null);
		if (prevHandle !== void 0) device.gl.bindFramebuffer(36160, prevHandle);
		if (destroyFramebuffer) framebuffer.destroy();
	}
}
/**
* Copies data from a Framebuffer or a Texture object into a Buffer object.
* NOTE: doesn't wait for copy to be complete, it programs GPU to perform a DMA transfer.
export function readPixelsToBuffer(
source: Framebuffer | Texture,
options?: {
sourceX?: number;
sourceY?: number;
sourceFormat?: number;
target?: Buffer; // A new Buffer object is created when not provided.
targetByteOffset?: number; // byte offset in buffer object
// following parameters are auto deduced if not provided
sourceWidth?: number;
sourceHeight?: number;
sourceType?: number;
}
): Buffer
*/
/**
* Copy a rectangle from a Framebuffer or Texture object into a texture (at an offset)
*/
function _copyTextureToTexture(device, options) {
	const { sourceTexture, destinationMipLevel = 0, origin = [0, 0], destinationOrigin = [
		0,
		0,
		0
	], destinationTexture } = options;
	let { width = options.destinationTexture.width, height = options.destinationTexture.height } = options;
	const { framebuffer, destroyFramebuffer } = getFramebuffer$1(sourceTexture);
	const [sourceX = 0, sourceY = 0] = origin;
	const [destinationX, destinationY, destinationZ] = destinationOrigin;
	const prevHandle = device.gl.bindFramebuffer(36160, framebuffer.handle);
	let texture;
	let textureTarget;
	if (destinationTexture instanceof WEBGLTexture) {
		texture = destinationTexture;
		width = Number.isFinite(width) ? width : texture.width;
		height = Number.isFinite(height) ? height : texture.height;
		texture._bind(0);
		textureTarget = texture.glTarget;
	} else throw new Error("invalid destination");
	switch (textureTarget) {
		case 3553:
		case 34067:
			device.gl.copyTexSubImage2D(textureTarget, destinationMipLevel, destinationX, destinationY, sourceX, sourceY, width, height);
			break;
		case 35866:
		case 32879:
			device.gl.copyTexSubImage3D(textureTarget, destinationMipLevel, destinationX, destinationY, destinationZ, sourceX, sourceY, width, height);
			break;
		default:
	}
	if (texture) texture._unbind();
	device.gl.bindFramebuffer(36160, prevHandle);
	if (destroyFramebuffer) framebuffer.destroy();
}
/** Wrap a texture in a framebuffer so that we can use WebGL APIs that work on framebuffers */
function getFramebuffer$1(source) {
	if (source instanceof Texture) {
		const { width, height, id } = source;
		return {
			framebuffer: source.device.createFramebuffer({
				id: `framebuffer-for-${id}`,
				width,
				height,
				colorAttachments: [source]
			}),
			destroyFramebuffer: true
		};
	}
	return {
		framebuffer: source,
		destroyFramebuffer: false
	};
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/resources/webgl-render-pass.js
var COLOR_CHANNELS = [
	1,
	2,
	4,
	8
];
var WEBGLRenderPass = class extends RenderPass {
	device;
	handle = null;
	/** Parameters that should be applied before each draw call */
	glParameters = {};
	constructor(device, props) {
		super(device, props);
		this.device = device;
		const webglFramebuffer = this.props.framebuffer;
		const isDefaultFramebuffer = !webglFramebuffer || webglFramebuffer.handle === null;
		if (isDefaultFramebuffer) device.getDefaultCanvasContext()._resizeDrawingBufferIfNeeded();
		let viewport;
		if (!props?.parameters?.viewport) if (!isDefaultFramebuffer && webglFramebuffer) {
			const { width, height } = webglFramebuffer;
			viewport = [
				0,
				0,
				width,
				height
			];
		} else {
			const [width, height] = device.getDefaultCanvasContext().getDrawingBufferSize();
			viewport = [
				0,
				0,
				width,
				height
			];
		}
		this.device.pushState();
		this.setParameters({
			viewport,
			...this.props.parameters
		});
		if (!isDefaultFramebuffer && webglFramebuffer?.colorAttachments.length) {
			const drawBuffers = webglFramebuffer.colorAttachments.map((_, i) => 36064 + i);
			this.device.gl.drawBuffers(drawBuffers);
		} else if (isDefaultFramebuffer) this.device.gl.drawBuffers([1029]);
		this.clear();
		if (this.props.timestampQuerySet && this.props.beginTimestampIndex !== void 0) this.props.timestampQuerySet.writeTimestamp(this.props.beginTimestampIndex);
	}
	end() {
		if (this.destroyed) return;
		if (this.props.timestampQuerySet && this.props.endTimestampIndex !== void 0) this.props.timestampQuerySet.writeTimestamp(this.props.endTimestampIndex);
		this.device.popState();
		this.destroy();
	}
	pushDebugGroup(groupLabel) {}
	popDebugGroup() {}
	insertDebugMarker(markerLabel) {}
	/**
	* Maps RenderPass parameters to GL parameters
	*/
	setParameters(parameters = {}) {
		const glParameters = { ...this.glParameters };
		glParameters.framebuffer = this.props.framebuffer || null;
		if (this.props.depthReadOnly) glParameters.depthMask = !this.props.depthReadOnly;
		glParameters.stencilMask = this.props.stencilReadOnly ? 0 : 1;
		glParameters[35977] = this.props.discard;
		if (parameters.viewport) if (parameters.viewport.length >= 6) {
			glParameters.viewport = parameters.viewport.slice(0, 4);
			glParameters.depthRange = [parameters.viewport[4], parameters.viewport[5]];
		} else glParameters.viewport = parameters.viewport;
		if (parameters.scissorRect) {
			glParameters.scissorTest = true;
			glParameters.scissor = parameters.scissorRect;
		}
		if (parameters.blendConstant) glParameters.blendColor = parameters.blendConstant;
		if (parameters.stencilReference !== void 0) {
			glParameters[2967] = parameters.stencilReference;
			glParameters[36003] = parameters.stencilReference;
		}
		if ("colorMask" in parameters) glParameters.colorMask = COLOR_CHANNELS.map((channel) => Boolean(channel & parameters.colorMask));
		this.glParameters = glParameters;
		setGLParameters(this.device.gl, glParameters);
	}
	beginOcclusionQuery(queryIndex) {
		this.props.occlusionQuerySet?.beginOcclusionQuery();
	}
	endOcclusionQuery() {
		this.props.occlusionQuerySet?.endOcclusionQuery();
	}
	/**
	* Optionally clears depth, color and stencil buffers based on parameters
	*/
	clear() {
		const glParameters = { ...this.glParameters };
		let clearMask = 0;
		if (this.props.clearColors) this.props.clearColors.forEach((color, drawBufferIndex) => {
			if (color) this.clearColorBuffer(drawBufferIndex, color);
		});
		if (this.props.clearColor !== false && this.props.clearColors === void 0) {
			clearMask |= 16384;
			glParameters.clearColor = this.props.clearColor;
		}
		if (this.props.clearDepth !== false) {
			clearMask |= 256;
			glParameters.clearDepth = this.props.clearDepth;
		}
		if (this.props.clearStencil !== false) {
			clearMask |= 1024;
			glParameters.clearStencil = this.props.clearStencil;
		}
		if (clearMask !== 0) withGLParameters(this.device.gl, glParameters, () => {
			this.device.gl.clear(clearMask);
		});
	}
	/**
	* WebGL2 - clear a specific color buffer
	*/
	clearColorBuffer(drawBuffer = 0, value = [
		0,
		0,
		0,
		0
	]) {
		withGLParameters(this.device.gl, { framebuffer: this.props.framebuffer }, () => {
			switch (value.constructor) {
				case Int8Array:
				case Int16Array:
				case Int32Array:
					this.device.gl.clearBufferiv(6144, drawBuffer, value);
					break;
				case Uint8Array:
				case Uint8ClampedArray:
				case Uint16Array:
				case Uint32Array:
					this.device.gl.clearBufferuiv(6144, drawBuffer, value);
					break;
				case Float32Array:
					this.device.gl.clearBufferfv(6144, drawBuffer, value);
					break;
				default: throw new Error("clearColorBuffer: color must be typed array");
			}
		});
	}
};
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/resources/webgl-command-encoder.js
var WEBGLCommandEncoder = class extends CommandEncoder {
	device;
	handle = null;
	commandBuffer;
	constructor(device, props) {
		super(device, props);
		this.device = device;
		this.commandBuffer = new WEBGLCommandBuffer(device, { id: `${this.props.id}-command-buffer` });
	}
	destroy() {
		this.destroyResource();
	}
	finish(props) {
		if (props?.id && this.commandBuffer.id !== props.id) {
			this.commandBuffer.id = props.id;
			this.commandBuffer.props.id = props.id;
		}
		this.destroy();
		return this.commandBuffer;
	}
	beginRenderPass(props = {}) {
		return new WEBGLRenderPass(this.device, this._applyTimeProfilingToPassProps(props));
	}
	beginComputePass(props = {}) {
		throw new Error("ComputePass not supported in WebGL");
	}
	copyBufferToBuffer(options) {
		this.commandBuffer.commands.push({
			name: "copy-buffer-to-buffer",
			options
		});
	}
	copyBufferToTexture(options) {
		this.commandBuffer.commands.push({
			name: "copy-buffer-to-texture",
			options
		});
	}
	copyTextureToBuffer(options) {
		this.commandBuffer.commands.push({
			name: "copy-texture-to-buffer",
			options
		});
	}
	copyTextureToTexture(options) {
		this.commandBuffer.commands.push({
			name: "copy-texture-to-texture",
			options
		});
	}
	pushDebugGroup(groupLabel) {}
	popDebugGroup() {}
	insertDebugMarker(markerLabel) {}
	resolveQuerySet(_querySet, _destination, _options) {
		throw new Error("resolveQuerySet is not supported in WebGL");
	}
	writeTimestamp(querySet, queryIndex) {
		querySet.writeTimestamp(queryIndex);
	}
};
//#endregion
//#region node_modules/@luma.gl/webgl/dist/utils/fill-array.js
function fillArray(options) {
	const { target, source, start = 0, count = 1 } = options;
	const length = source.length;
	const total = count * length;
	let copied = 0;
	for (let i = start; copied < length; copied++) target[i++] = source[copied] ?? 0;
	while (copied < total) if (copied < total - copied) {
		target.copyWithin(start + copied, start, start + copied);
		copied *= 2;
	} else {
		target.copyWithin(start + copied, start, start + total - copied);
		copied = total;
	}
	return options.target;
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/resources/webgl-vertex-array.js
/** VertexArrayObject wrapper */
var WEBGLVertexArray = class WEBGLVertexArray extends VertexArray {
	get [Symbol.toStringTag]() {
		return "VertexArray";
	}
	device;
	handle;
	/** Attribute 0 buffer constant */
	buffer = null;
	bufferValue = null;
	/** * Attribute 0 can not be disable on most desktop OpenGL based browsers */
	static isConstantAttributeZeroSupported(device) {
		return getBrowser() === "Chrome";
	}
	constructor(device, props) {
		super(device, props);
		this.device = device;
		this.handle = this.device.gl.createVertexArray();
	}
	destroy() {
		super.destroy();
		if (this.buffer) this.buffer?.destroy();
		if (this.handle) {
			this.device.gl.deleteVertexArray(this.handle);
			this.handle = void 0;
		}
	}
	/**
	// Set (bind/unbind) an elements buffer, for indexed rendering.
	// Must be a Buffer bound to GL.ELEMENT_ARRAY_BUFFER or null. Constants not supported
	*
	* @param elementBuffer
	*/
	setIndexBuffer(indexBuffer) {
		const buffer = indexBuffer;
		if (buffer && buffer.glTarget !== 34963) throw new Error("Use .setBuffer()");
		this.device.gl.bindVertexArray(this.handle);
		this.device.gl.bindBuffer(34963, buffer ? buffer.handle : null);
		this.indexBuffer = buffer;
		this.device.gl.bindVertexArray(null);
	}
	/** Set a location in vertex attributes array to a buffer, enables the location, sets divisor */
	setBuffer(location, attributeBuffer) {
		const buffer = attributeBuffer;
		if (buffer.glTarget === 34963) throw new Error("Use .setIndexBuffer()");
		const { size, type, stride, offset, normalized, integer, divisor } = this._getAccessor(location);
		this.device.gl.bindVertexArray(this.handle);
		this.device.gl.bindBuffer(34962, buffer.handle);
		if (integer) this.device.gl.vertexAttribIPointer(location, size, type, stride, offset);
		else this.device.gl.vertexAttribPointer(location, size, type, normalized, stride, offset);
		this.device.gl.bindBuffer(34962, null);
		this.device.gl.enableVertexAttribArray(location);
		this.device.gl.vertexAttribDivisor(location, divisor || 0);
		this.attributes[location] = buffer;
		this.device.gl.bindVertexArray(null);
	}
	/** Set a location in vertex attributes array to a constant value, disables the location */
	setConstantWebGL(location, value) {
		this._enable(location, false);
		this.attributes[location] = value;
	}
	bindBeforeRender() {
		this.device.gl.bindVertexArray(this.handle);
		this._applyConstantAttributes();
	}
	unbindAfterRender() {
		this.device.gl.bindVertexArray(null);
	}
	/**
	* Constant attributes need to be reset before every draw call
	* Any attribute that is disabled in the current vertex array object
	* is read from the context's global constant value for that attribute location.
	* @note Constant attributes are only supported in WebGL, not in WebGPU
	*/
	_applyConstantAttributes() {
		for (let location = 0; location < this.maxVertexAttributes; ++location) {
			const constant = this.attributes[location];
			if (ArrayBuffer.isView(constant)) this.device.setConstantAttributeWebGL(location, constant);
		}
	}
	/**
	* Set a location in vertex attributes array to a buffer, enables the location, sets divisor
	* @note requires vertex array to be bound
	*/
	/** Get an accessor from the  */
	_getAccessor(location) {
		const attributeInfo = this.attributeInfos[location];
		if (!attributeInfo) throw new Error(`Unknown attribute location ${location}`);
		const glType = getGLFromVertexType(attributeInfo.bufferDataType);
		return {
			size: attributeInfo.bufferComponents,
			type: glType,
			stride: attributeInfo.byteStride,
			offset: attributeInfo.byteOffset,
			normalized: attributeInfo.normalized,
			integer: attributeInfo.integer,
			divisor: attributeInfo.stepMode === "instance" ? 1 : 0
		};
	}
	/**
	* Enabling an attribute location makes it reference the currently bound buffer
	* Disabling an attribute location makes it reference the global constant value
	* TODO - handle single values for size 1 attributes?
	* TODO - convert classic arrays based on known type?
	*/
	_enable(location, enable = true) {
		const canDisableAttribute = WEBGLVertexArray.isConstantAttributeZeroSupported(this.device) || location !== 0;
		if (enable || canDisableAttribute) {
			location = Number(location);
			this.device.gl.bindVertexArray(this.handle);
			if (enable) this.device.gl.enableVertexAttribArray(location);
			else this.device.gl.disableVertexAttribArray(location);
			this.device.gl.bindVertexArray(null);
		}
	}
	/**
	* Provide a means to create a buffer that is equivalent to a constant.
	* NOTE: Desktop OpenGL cannot disable attribute 0.
	* https://stackoverflow.com/questions/20305231/webgl-warning-attribute-0-is-disabled-
	* this-has-significant-performance-penalty
	*/
	getConstantBuffer(elementCount, value) {
		const constantValue = normalizeConstantArrayValue(value);
		const byteLength = constantValue.byteLength * elementCount;
		const length = constantValue.length * elementCount;
		if (this.buffer && byteLength !== this.buffer.byteLength) throw new Error(`Buffer size is immutable, byte length ${byteLength} !== ${this.buffer.byteLength}.`);
		let updateNeeded = !this.buffer;
		this.buffer = this.buffer || this.device.createBuffer({ byteLength });
		updateNeeded ||= !compareConstantArrayValues$1(constantValue, this.bufferValue);
		if (updateNeeded) {
			const typedArray = getScratchArray(value.constructor, length);
			fillArray({
				target: typedArray,
				source: constantValue,
				start: 0,
				count: length
			});
			this.buffer.write(typedArray);
			this.bufferValue = value;
		}
		return this.buffer;
	}
};
/**
* TODO - convert Arrays based on known type? (read type from accessor, don't assume Float32Array)
* TODO - handle single values for size 1 attributes?
*/
function normalizeConstantArrayValue(arrayValue) {
	if (Array.isArray(arrayValue)) return new Float32Array(arrayValue);
	return arrayValue;
}
/**
*
*/
function compareConstantArrayValues$1(v1, v2) {
	if (!v1 || !v2 || v1.length !== v2.length || v1.constructor !== v2.constructor) return false;
	for (let i = 0; i < v1.length; ++i) if (v1[i] !== v2[i]) return false;
	return true;
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/resources/webgl-transform-feedback.js
var WEBGLTransformFeedback = class extends TransformFeedback {
	device;
	gl;
	handle;
	/**
	* NOTE: The Model already has this information while drawing, but
	* TransformFeedback currently needs it internally, to look up
	* varying information outside of a draw() call.
	*/
	layout;
	buffers = {};
	unusedBuffers = {};
	/**
	* Allows us to avoid a Chrome bug where a buffer that is already bound to a
	* different target cannot be bound to 'TRANSFORM_FEEDBACK_BUFFER' target.
	* This a major workaround, see: https://github.com/KhronosGroup/WebGL/issues/2346
	*/
	bindOnUse = true;
	_bound = false;
	constructor(device, props) {
		super(device, props);
		this.device = device;
		this.gl = device.gl;
		this.handle = this.props.handle || this.gl.createTransformFeedback();
		this.layout = this.props.layout;
		if (props.buffers) this.setBuffers(props.buffers);
		Object.seal(this);
	}
	destroy() {
		this.gl.deleteTransformFeedback(this.handle);
		super.destroy();
	}
	begin(topology = "point-list") {
		this.gl.bindTransformFeedback(36386, this.handle);
		if (this.bindOnUse) this._bindBuffers();
		this.gl.beginTransformFeedback(getGLPrimitive(topology));
	}
	end() {
		this.gl.endTransformFeedback();
		if (this.bindOnUse) this._unbindBuffers();
		this.gl.bindTransformFeedback(36386, null);
	}
	setBuffers(buffers) {
		this.buffers = {};
		this.unusedBuffers = {};
		this.bind(() => {
			for (const [bufferName, buffer] of Object.entries(buffers)) this.setBuffer(bufferName, buffer);
		});
	}
	setBuffer(locationOrName, bufferOrRange) {
		const location = this._getVaryingIndex(locationOrName);
		const { buffer, byteLength, byteOffset } = this._getBufferRange(bufferOrRange);
		if (location < 0) {
			this.unusedBuffers[locationOrName] = buffer;
			log.warn(`${this.id} unusedBuffers varying buffer ${locationOrName}`)();
			return;
		}
		this.buffers[location] = {
			buffer,
			byteLength,
			byteOffset
		};
		if (!this.bindOnUse) this._bindBuffer(location, buffer, byteOffset, byteLength);
	}
	getBuffer(locationOrName) {
		if (isIndex(locationOrName)) return this.buffers[locationOrName] || null;
		const location = this._getVaryingIndex(locationOrName);
		return this.buffers[location] ?? null;
	}
	bind(funcOrHandle = this.handle) {
		if (typeof funcOrHandle !== "function") {
			this.gl.bindTransformFeedback(36386, funcOrHandle);
			return this;
		}
		let value;
		if (!this._bound) {
			this.gl.bindTransformFeedback(36386, this.handle);
			this._bound = true;
			value = funcOrHandle();
			this._bound = false;
			this.gl.bindTransformFeedback(36386, null);
		} else value = funcOrHandle();
		return value;
	}
	unbind() {
		this.bind(null);
	}
	/** Extract offsets for bindBufferRange */
	_getBufferRange(bufferOrRange) {
		if (bufferOrRange instanceof WEBGLBuffer) return {
			buffer: bufferOrRange,
			byteOffset: 0,
			byteLength: bufferOrRange.byteLength
		};
		const { buffer, byteOffset = 0, byteLength = bufferOrRange.buffer.byteLength } = bufferOrRange;
		return {
			buffer,
			byteOffset,
			byteLength
		};
	}
	_getVaryingIndex(locationOrName) {
		if (isIndex(locationOrName)) return Number(locationOrName);
		for (const varying of this.layout.varyings || []) if (locationOrName === varying.name) return varying.location;
		return -1;
	}
	/**
	* Need to avoid chrome bug where buffer that is already bound to a different target
	* cannot be bound to 'TRANSFORM_FEEDBACK_BUFFER' target.
	*/
	_bindBuffers() {
		for (const [bufferIndex, bufferEntry] of Object.entries(this.buffers)) {
			const { buffer, byteLength, byteOffset } = this._getBufferRange(bufferEntry);
			this._bindBuffer(Number(bufferIndex), buffer, byteOffset, byteLength);
		}
	}
	_unbindBuffers() {
		for (const bufferIndex in this.buffers) this.gl.bindBufferBase(35982, Number(bufferIndex), null);
	}
	_bindBuffer(index, buffer, byteOffset = 0, byteLength) {
		const handle = buffer && buffer.handle;
		if (!handle || byteLength === void 0) this.gl.bindBufferBase(35982, index, handle);
		else this.gl.bindBufferRange(35982, index, handle, byteOffset, byteLength);
	}
};
/**
* Returns true if the given value is an integer, or a string that
* trivially converts to an integer (only numeric characters).
*/
function isIndex(value) {
	if (typeof value === "number") return Number.isInteger(value);
	return /^\d+$/.test(value);
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/resources/webgl-query-set.js
/**
* Asynchronous queries for different kinds of information
*/
var WEBGLQuerySet = class extends QuerySet {
	device;
	handle;
	_timestampPairs = [];
	_pendingReads = /* @__PURE__ */ new Set();
	_occlusionQuery = null;
	_occlusionActive = false;
	get [Symbol.toStringTag]() {
		return "QuerySet";
	}
	constructor(device, props) {
		super(device, props);
		this.device = device;
		if (props.type === "timestamp") {
			if (props.count < 2) throw new Error("Timestamp QuerySet requires at least two query slots");
			this._timestampPairs = new Array(Math.ceil(props.count / 2)).fill(null).map(() => ({
				activeQuery: null,
				completedQueries: []
			}));
			this.handle = null;
		} else {
			if (props.count > 1) throw new Error("WebGL occlusion QuerySet can only have one value");
			const handle = this.device.gl.createQuery();
			if (!handle) throw new Error("WebGL query not supported");
			this.handle = handle;
		}
		Object.seal(this);
	}
	destroy() {
		if (this.destroyed) return;
		if (this.handle) this.device.gl.deleteQuery(this.handle);
		for (const pair of this._timestampPairs) {
			if (pair.activeQuery) {
				this._cancelPendingQuery(pair.activeQuery);
				this.device.gl.deleteQuery(pair.activeQuery.handle);
			}
			for (const query of pair.completedQueries) {
				this._cancelPendingQuery(query);
				this.device.gl.deleteQuery(query.handle);
			}
		}
		if (this._occlusionQuery) {
			this._cancelPendingQuery(this._occlusionQuery);
			this.device.gl.deleteQuery(this._occlusionQuery.handle);
		}
		for (const query of Array.from(this._pendingReads)) this._cancelPendingQuery(query);
		this.destroyResource();
	}
	isResultAvailable(queryIndex) {
		if (this.props.type === "timestamp") {
			if (queryIndex === void 0) return this._timestampPairs.some((_, pairIndex) => this._isTimestampPairAvailable(pairIndex));
			return this._isTimestampPairAvailable(this._getTimestampPairIndex(queryIndex));
		}
		if (!this._occlusionQuery) return false;
		return this._pollQueryAvailability(this._occlusionQuery);
	}
	async readResults(options) {
		const firstQuery = options?.firstQuery || 0;
		const queryCount = options?.queryCount || this.props.count - firstQuery;
		this._validateRange(firstQuery, queryCount);
		if (this.props.type === "timestamp") {
			const results = new Array(queryCount).fill(0n);
			const startPairIndex = Math.floor(firstQuery / 2);
			const endPairIndex = Math.floor((firstQuery + queryCount - 1) / 2);
			for (let pairIndex = startPairIndex; pairIndex <= endPairIndex; pairIndex++) {
				const duration = await this._consumeTimestampPairResult(pairIndex);
				const beginSlot = pairIndex * 2;
				const endSlot = beginSlot + 1;
				if (beginSlot >= firstQuery && beginSlot < firstQuery + queryCount) results[beginSlot - firstQuery] = 0n;
				if (endSlot >= firstQuery && endSlot < firstQuery + queryCount) results[endSlot - firstQuery] = duration;
			}
			return results;
		}
		if (!this._occlusionQuery) throw new Error("Occlusion query has not been started");
		return [await this._consumeQueryResult(this._occlusionQuery)];
	}
	async readTimestampDuration(beginIndex, endIndex) {
		if (this.props.type !== "timestamp") throw new Error("Timestamp durations require a timestamp QuerySet");
		if (beginIndex < 0 || endIndex >= this.props.count || endIndex <= beginIndex) throw new Error("Timestamp duration range is out of bounds");
		if (beginIndex % 2 !== 0 || endIndex !== beginIndex + 1) throw new Error("WebGL timestamp durations require adjacent even/odd query indices");
		const result = await this._consumeTimestampPairResult(this._getTimestampPairIndex(beginIndex));
		return Number(result) / 1e6;
	}
	beginOcclusionQuery() {
		if (this.props.type !== "occlusion") throw new Error("Occlusion queries require an occlusion QuerySet");
		if (!this.handle) throw new Error("WebGL occlusion query is not available");
		if (this._occlusionActive) throw new Error("Occlusion query is already active");
		this.device.gl.beginQuery(35887, this.handle);
		this._occlusionQuery = {
			handle: this.handle,
			promise: null,
			result: null,
			disjoint: false,
			cancelled: false,
			pollRequestId: null,
			resolve: null,
			reject: null
		};
		this._occlusionActive = true;
	}
	endOcclusionQuery() {
		if (!this._occlusionActive) throw new Error("Occlusion query is not active");
		this.device.gl.endQuery(35887);
		this._occlusionActive = false;
	}
	writeTimestamp(queryIndex) {
		if (this.props.type !== "timestamp") throw new Error("Timestamp writes require a timestamp QuerySet");
		const pairIndex = this._getTimestampPairIndex(queryIndex);
		const pair = this._timestampPairs[pairIndex];
		if (queryIndex % 2 === 0) {
			if (pair.activeQuery) throw new Error("Timestamp query pair is already active");
			const handle = this.device.gl.createQuery();
			if (!handle) throw new Error("WebGL query not supported");
			const query = {
				handle,
				promise: null,
				result: null,
				disjoint: false,
				cancelled: false,
				pollRequestId: null,
				resolve: null,
				reject: null
			};
			this.device.gl.beginQuery(35007, handle);
			pair.activeQuery = query;
			return;
		}
		if (!pair.activeQuery) throw new Error("Timestamp query pair was ended before it was started");
		this.device.gl.endQuery(35007);
		pair.completedQueries.push(pair.activeQuery);
		pair.activeQuery = null;
	}
	_validateRange(firstQuery, queryCount) {
		if (firstQuery < 0 || queryCount < 0 || firstQuery + queryCount > this.props.count) throw new Error("Query read range is out of bounds");
	}
	_getTimestampPairIndex(queryIndex) {
		if (queryIndex < 0 || queryIndex >= this.props.count) throw new Error("Query index is out of bounds");
		return Math.floor(queryIndex / 2);
	}
	_isTimestampPairAvailable(pairIndex) {
		const pair = this._timestampPairs[pairIndex];
		if (!pair || pair.completedQueries.length === 0) return false;
		return this._pollQueryAvailability(pair.completedQueries[0]);
	}
	_pollQueryAvailability(query) {
		if (query.cancelled || this.destroyed) {
			query.result = 0n;
			return true;
		}
		if (query.result !== null || query.disjoint) return true;
		if (!this.device.gl.getQueryParameter(query.handle, 34919)) return false;
		const isDisjoint = Boolean(this.device.gl.getParameter(36795));
		query.disjoint = isDisjoint;
		query.result = isDisjoint ? 0n : BigInt(this.device.gl.getQueryParameter(query.handle, 34918));
		return true;
	}
	async _consumeTimestampPairResult(pairIndex) {
		const pair = this._timestampPairs[pairIndex];
		if (!pair || pair.completedQueries.length === 0) throw new Error("Timestamp query pair has no completed result");
		const query = pair.completedQueries.shift();
		try {
			return await this._consumeQueryResult(query);
		} finally {
			this.device.gl.deleteQuery(query.handle);
		}
	}
	_consumeQueryResult(query) {
		if (query.promise) return query.promise;
		this._pendingReads.add(query);
		query.promise = new Promise((resolve, reject) => {
			query.resolve = resolve;
			query.reject = reject;
			const poll = () => {
				query.pollRequestId = null;
				if (query.cancelled || this.destroyed) {
					this._pendingReads.delete(query);
					query.promise = null;
					query.resolve = null;
					query.reject = null;
					resolve(0n);
					return;
				}
				if (!this._pollQueryAvailability(query)) {
					query.pollRequestId = this._requestAnimationFrame(poll);
					return;
				}
				this._pendingReads.delete(query);
				query.promise = null;
				query.resolve = null;
				query.reject = null;
				if (query.disjoint) reject(/* @__PURE__ */ new Error("GPU timestamp query was invalidated by a disjoint event"));
				else resolve(query.result || 0n);
			};
			poll();
		});
		return query.promise;
	}
	_cancelPendingQuery(query) {
		this._pendingReads.delete(query);
		query.cancelled = true;
		if (query.pollRequestId !== null) {
			this._cancelAnimationFrame(query.pollRequestId);
			query.pollRequestId = null;
		}
		if (query.resolve) {
			const resolve = query.resolve;
			query.promise = null;
			query.resolve = null;
			query.reject = null;
			resolve(0n);
		}
	}
	_requestAnimationFrame(callback) {
		return requestAnimationFrame(callback);
	}
	_cancelAnimationFrame(requestId) {
		cancelAnimationFrame(requestId);
	}
};
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/resources/webgl-fence.js
/** WebGL fence implemented with gl.fenceSync */
var WEBGLFence = class extends Fence {
	device;
	gl;
	handle;
	signaled;
	_signaled = false;
	constructor(device, props = {}) {
		super(device, {});
		this.device = device;
		this.gl = device.gl;
		const sync = this.props.handle || this.gl.fenceSync(this.gl.SYNC_GPU_COMMANDS_COMPLETE, 0);
		if (!sync) throw new Error("Failed to create WebGL fence");
		this.handle = sync;
		this.signaled = new Promise((resolve) => {
			const poll = () => {
				const status = this.gl.clientWaitSync(this.handle, 0, 0);
				if (status === this.gl.ALREADY_SIGNALED || status === this.gl.CONDITION_SATISFIED) {
					this._signaled = true;
					resolve();
				} else setTimeout(poll, 1);
			};
			poll();
		});
	}
	isSignaled() {
		if (this._signaled) return true;
		const status = this.gl.getSyncParameter(this.handle, this.gl.SYNC_STATUS);
		this._signaled = status === this.gl.SIGNALED;
		return this._signaled;
	}
	destroy() {
		if (!this.destroyed) this.gl.deleteSync(this.handle);
	}
};
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/helpers/format-utils.js
function glFormatToComponents(format) {
	switch (format) {
		case 6406:
		case 33326:
		case 6403:
		case 36244: return 1;
		case 33339:
		case 33340:
		case 33328:
		case 33320:
		case 33319: return 2;
		case 6407:
		case 36248:
		case 34837: return 3;
		case 6408:
		case 36249:
		case 34836: return 4;
		default: return 0;
	}
}
function glTypeToBytes(type) {
	switch (type) {
		case 5121: return 1;
		case 33635:
		case 32819:
		case 32820: return 2;
		case 5126: return 4;
		default: return 0;
	}
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/helpers/webgl-texture-utils.js
/**
* Copies data from a type  or a Texture object into ArrayBuffer object.
* App can provide targetPixelArray or have it auto allocated by this method
*  newly allocated by this method unless provided by app.
* @deprecated Use CommandEncoder.copyTextureToBuffer and Buffer.read
* @note Slow requires roundtrip to GPU
*
* @param source
* @param options
* @returns pixel array,
*/
function readPixelsToArray(source, options) {
	const { sourceX = 0, sourceY = 0, sourceAttachment = 0 } = options || {};
	let { target = null, sourceWidth, sourceHeight, sourceDepth, sourceFormat, sourceType } = options || {};
	const { framebuffer, deleteFramebuffer } = getFramebuffer(source);
	const { gl, handle } = framebuffer;
	sourceWidth ||= framebuffer.width;
	sourceHeight ||= framebuffer.height;
	const texture = framebuffer.colorAttachments[sourceAttachment]?.texture;
	if (!texture) throw new Error(`Invalid framebuffer attachment ${sourceAttachment}`);
	sourceDepth = texture?.depth || 1;
	sourceFormat ||= texture?.glFormat || 6408;
	sourceType ||= texture?.glType || 5121;
	target = getPixelArray(target, sourceType, sourceFormat, sourceWidth, sourceHeight, sourceDepth);
	const signedType = dataTypeDecoder.getDataType(target);
	sourceType = sourceType || convertDataTypeToGLDataType(signedType);
	const prevHandle = gl.bindFramebuffer(36160, handle);
	gl.readBuffer(36064 + sourceAttachment);
	gl.readPixels(sourceX, sourceY, sourceWidth, sourceHeight, sourceFormat, sourceType, target);
	gl.readBuffer(36064);
	gl.bindFramebuffer(36160, prevHandle || null);
	if (deleteFramebuffer) framebuffer.destroy();
	return target;
}
/**
* Copies data from a Framebuffer or a Texture object into a Buffer object.
* NOTE: doesn't wait for copy to be complete, it programs GPU to perform a DMA transffer.
* @deprecated Use CommandEncoder
* @param source
* @param options
*/
function readPixelsToBuffer(source, options) {
	const { target, sourceX = 0, sourceY = 0, sourceFormat = 6408, targetByteOffset = 0 } = options || {};
	let { sourceWidth, sourceHeight, sourceType } = options || {};
	const { framebuffer, deleteFramebuffer } = getFramebuffer(source);
	sourceWidth = sourceWidth || framebuffer.width;
	sourceHeight = sourceHeight || framebuffer.height;
	const webglFramebuffer = framebuffer;
	sourceType = sourceType || 5121;
	let webglBufferTarget = target;
	if (!webglBufferTarget) {
		const components = glFormatToComponents(sourceFormat);
		const byteCount = glTypeToBytes(sourceType);
		const byteLength = targetByteOffset + sourceWidth * sourceHeight * components * byteCount;
		webglBufferTarget = webglFramebuffer.device.createBuffer({ byteLength });
	}
	const commandEncoder = source.device.createCommandEncoder();
	commandEncoder.copyTextureToBuffer({
		sourceTexture: source,
		width: sourceWidth,
		height: sourceHeight,
		origin: [sourceX, sourceY],
		destinationBuffer: webglBufferTarget,
		byteOffset: targetByteOffset
	});
	commandEncoder.destroy();
	if (deleteFramebuffer) framebuffer.destroy();
	return webglBufferTarget;
}
function getFramebuffer(source) {
	if (!(source instanceof Framebuffer)) return {
		framebuffer: toFramebuffer(source),
		deleteFramebuffer: true
	};
	return {
		framebuffer: source,
		deleteFramebuffer: false
	};
}
/**
* Wraps a given texture into a framebuffer object, that can be further used
* to read data from the texture object.
*/
function toFramebuffer(texture, props) {
	const { device, width, height, id } = texture;
	return device.createFramebuffer({
		...props,
		id: `framebuffer-for-${id}`,
		width,
		height,
		colorAttachments: [texture]
	});
}
function getPixelArray(pixelArray, glType, glFormat, width, height, depth) {
	if (pixelArray) return pixelArray;
	glType ||= 5121;
	const shaderType = convertGLDataTypeToDataType(glType);
	const ArrayType = dataTypeDecoder.getTypedArrayConstructor(shaderType);
	const components = glFormatToComponents(glFormat);
	return new ArrayType(width * height * components);
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/webgl-device.js
var webgl_device_exports = /* @__PURE__ */ __exportAll({ WebGLDevice: () => WebGLDevice });
/** WebGPU style Device API for a WebGL context */
var WebGLDevice = class WebGLDevice extends Device {
	static getDeviceFromContext(gl) {
		if (!gl) return null;
		return gl.luma?.device ?? null;
	}
	/** type of this device */
	type = "webgl";
	/** The underlying WebGL context */
	handle;
	features;
	limits;
	info;
	canvasContext;
	preferredColorFormat = "rgba8unorm";
	preferredDepthFormat = "depth24plus";
	commandEncoder;
	lost;
	_resolveContextLost;
	/** WebGL2 context. */
	gl;
	/** Store constants */
	_constants;
	/** State used by luma.gl classes - TODO - not used? */
	extensions;
	_polyfilled = false;
	/** Instance of Spector.js (if initialized) */
	spectorJS;
	get [Symbol.toStringTag]() {
		return "WebGLDevice";
	}
	toString() {
		return `${this[Symbol.toStringTag]}(${this.id})`;
	}
	isVertexFormatSupported(format) {
		switch (format) {
			case "unorm8x4-bgra": return false;
			default: return true;
		}
	}
	constructor(props) {
		super({
			...props,
			id: props.id || uid("webgl-device")
		});
		const canvasContextProps = Device._getCanvasContextProps(props);
		if (!canvasContextProps) throw new Error("WebGLDevice requires props.createCanvasContext to be set");
		const existingContext = canvasContextProps.canvas?.gl ?? null;
		let device = WebGLDevice.getDeviceFromContext(existingContext);
		if (device) throw new Error(`WebGL context already attached to device ${device.id}`);
		this.canvasContext = new WebGLCanvasContext(this, canvasContextProps);
		this.lost = new Promise((resolve) => {
			this._resolveContextLost = resolve;
		});
		const webglContextAttributes = { ...props.webgl };
		if (canvasContextProps.alphaMode === "premultiplied") webglContextAttributes.premultipliedAlpha = true;
		if (props.powerPreference !== void 0) webglContextAttributes.powerPreference = props.powerPreference;
		if (props.failIfMajorPerformanceCaveat !== void 0) webglContextAttributes.failIfMajorPerformanceCaveat = props.failIfMajorPerformanceCaveat;
		const gl = this.props._handle || createBrowserContext(this.canvasContext.canvas, {
			onContextLost: (event) => this._resolveContextLost?.({
				reason: "destroyed",
				message: "Entered sleep mode, or too many apps or browser tabs are using the GPU."
			}),
			onContextRestored: (event) => console.log("WebGL context restored")
		}, webglContextAttributes);
		if (!gl) throw new Error("WebGL context creation failed");
		device = WebGLDevice.getDeviceFromContext(gl);
		if (device) {
			if (props._reuseDevices) {
				log.log(1, `Not creating a new Device, instead returning a reference to Device ${device.id} already attached to WebGL context`, device)();
				this.canvasContext.destroy();
				device._reused = true;
				return device;
			}
			throw new Error(`WebGL context already attached to device ${device.id}`);
		}
		this.handle = gl;
		this.gl = gl;
		this.spectorJS = initializeSpectorJS({
			...this.props,
			gl: this.handle
		});
		const contextData = getWebGLContextData(this.handle);
		contextData.device = this;
		if (!contextData.extensions) contextData.extensions = {};
		this.extensions = contextData.extensions;
		this.info = getDeviceInfo(this.gl, this.extensions);
		this.limits = new WebGLDeviceLimits(this.gl);
		this.features = new WebGLDeviceFeatures(this.gl, this.extensions, this.props._disabledFeatures);
		if (this.props._initializeFeatures) this.features.initializeFeatures();
		new WebGLStateTracker(this.gl, { log: (...args) => log.log(1, ...args)() }).trackState(this.gl, { copyState: false });
		if (props.debug || props.debugWebGL) {
			this.gl = makeDebugContext(this.gl, {
				debugWebGL: true,
				traceWebGL: props.debugWebGL
			});
			log.warn("WebGL debug mode activated. Performance reduced.")();
		}
		if (props.debugWebGL) log.level = Math.max(log.level, 1);
		this.commandEncoder = new WEBGLCommandEncoder(this, { id: `${this}-command-encoder` });
		this.canvasContext._startObservers();
	}
	/**
	* Destroys the device
	*
	* @note "Detaches" from the WebGL context unless _reuseDevices is true.
	*
	* @note The underlying WebGL context is not immediately destroyed,
	* but may be destroyed later through normal JavaScript garbage collection.
	* This is a fundamental limitation since WebGL does not offer any
	* browser API for destroying WebGL contexts.
	*/
	destroy() {
		this.commandEncoder?.destroy();
		if (!this.props._reuseDevices && !this._reused) {
			const contextData = getWebGLContextData(this.handle);
			contextData.device = null;
		}
	}
	get isLost() {
		return this.gl.isContextLost();
	}
	createCanvasContext(props) {
		throw new Error("WebGL only supports a single canvas");
	}
	createPresentationContext(props) {
		return new WebGLPresentationContext(this, props || {});
	}
	createBuffer(props) {
		const newProps = this._normalizeBufferProps(props);
		return new WEBGLBuffer(this, newProps);
	}
	createTexture(props) {
		return new WEBGLTexture(this, props);
	}
	createExternalTexture(props) {
		throw new Error("createExternalTexture() not implemented");
	}
	createSampler(props) {
		return new WEBGLSampler(this, props);
	}
	createShader(props) {
		return new WEBGLShader(this, props);
	}
	createFramebuffer(props) {
		return new WEBGLFramebuffer(this, props);
	}
	createVertexArray(props) {
		return new WEBGLVertexArray(this, props);
	}
	createTransformFeedback(props) {
		return new WEBGLTransformFeedback(this, props);
	}
	createQuerySet(props) {
		return new WEBGLQuerySet(this, props);
	}
	createFence() {
		return new WEBGLFence(this);
	}
	createRenderPipeline(props) {
		return new WEBGLRenderPipeline(this, props);
	}
	_createSharedRenderPipelineWebGL(props) {
		return new WEBGLSharedRenderPipeline(this, props);
	}
	createComputePipeline(props) {
		throw new Error("ComputePipeline not supported in WebGL");
	}
	createCommandEncoder(props = {}) {
		return new WEBGLCommandEncoder(this, props);
	}
	/**
	* Offscreen Canvas Support: Commit the frame
	* https://developer.mozilla.org/en-US/docs/Web/API/WebGL2RenderingContext/commit
	* Chrome's offscreen canvas does not require gl.commit
	*/
	submit(commandBuffer) {
		let submittedCommandEncoder = null;
		if (!commandBuffer) ({submittedCommandEncoder, commandBuffer} = this._finalizeDefaultCommandEncoderForSubmit());
		try {
			commandBuffer._executeCommands();
			if (submittedCommandEncoder) submittedCommandEncoder.resolveTimeProfilingQuerySet().then(() => {
				this.commandEncoder._gpuTimeMs = submittedCommandEncoder._gpuTimeMs;
			}).catch(() => {});
		} finally {
			commandBuffer.destroy();
		}
	}
	_finalizeDefaultCommandEncoderForSubmit() {
		const submittedCommandEncoder = this.commandEncoder;
		const commandBuffer = submittedCommandEncoder.finish();
		this.commandEncoder.destroy();
		this.commandEncoder = this.createCommandEncoder({
			id: submittedCommandEncoder.props.id,
			timeProfilingQuerySet: submittedCommandEncoder.getTimeProfilingQuerySet()
		});
		return {
			submittedCommandEncoder,
			commandBuffer
		};
	}
	/** @deprecated - should use command encoder */
	readPixelsToArrayWebGL(source, options) {
		return readPixelsToArray(source, options);
	}
	/** @deprecated - should use command encoder */
	readPixelsToBufferWebGL(source, options) {
		return readPixelsToBuffer(source, options);
	}
	setParametersWebGL(parameters) {
		setGLParameters(this.gl, parameters);
	}
	getParametersWebGL(parameters) {
		return getGLParameters(this.gl, parameters);
	}
	withParametersWebGL(parameters, func) {
		return withGLParameters(this.gl, parameters, func);
	}
	resetWebGL() {
		log.warn("WebGLDevice.resetWebGL is deprecated, use only for debugging")();
		resetGLParameters(this.gl);
	}
	_getDeviceSpecificTextureFormatCapabilities(capabilities) {
		return getTextureFormatCapabilitiesWebGL(this.gl, capabilities, this.extensions);
	}
	/**
	* Triggers device (or WebGL context) loss.
	* @note primarily intended for testing how application reacts to device loss
	*/
	loseDevice() {
		let deviceLossTriggered = false;
		const ext = this.getExtension("WEBGL_lose_context").WEBGL_lose_context;
		if (ext) {
			deviceLossTriggered = true;
			ext.loseContext();
		}
		this._resolveContextLost?.({
			reason: "destroyed",
			message: "Application triggered context loss"
		});
		return deviceLossTriggered;
	}
	/** Save current WebGL context state onto an internal stack */
	pushState() {
		WebGLStateTracker.get(this.gl).push();
	}
	/** Restores previously saved context state */
	popState() {
		WebGLStateTracker.get(this.gl).pop();
	}
	/**
	* Returns the GL.<KEY> constant that corresponds to a numeric value of a GL constant
	* Be aware that there are some duplicates especially for constants that are 0,
	* so this isn't guaranteed to return the right key in all cases.
	*/
	getGLKey(value, options) {
		const number = Number(value);
		for (const key in this.gl) if (this.gl[key] === number) return `GL.${key}`;
		return options?.emptyIfUnknown ? "" : String(value);
	}
	/**
	* Returns a map with any GL.<KEY> constants mapped to strings, both for keys and values
	*/
	getGLKeys(glParameters) {
		const opts = { emptyIfUnknown: true };
		return Object.entries(glParameters).reduce((keys, [key, value]) => {
			keys[`${key}:${this.getGLKey(key, opts)}`] = `${value}:${this.getGLKey(value, opts)}`;
			return keys;
		}, {});
	}
	/**
	* Set a constant value for a location. Disabled attributes at that location will read from this value
	* @note WebGL constants are stored globally on the WebGL context, not the VertexArray
	* so they need to be updated before every render
	* @todo - remember/cache values to avoid setting them unnecessarily?
	*/
	setConstantAttributeWebGL(location, constant) {
		const maxVertexAttributes = this.limits.maxVertexAttributes;
		this._constants = this._constants || new Array(maxVertexAttributes).fill(null);
		const currentConstant = this._constants[location];
		if (currentConstant && compareConstantArrayValues(currentConstant, constant)) log.info(1, `setConstantAttributeWebGL(${location}) could have been skipped, value unchanged`)();
		this._constants[location] = constant;
		switch (constant.constructor) {
			case Float32Array:
				setConstantFloatArray(this, location, constant);
				break;
			case Int32Array:
				setConstantIntArray(this, location, constant);
				break;
			case Uint32Array:
				setConstantUintArray(this, location, constant);
				break;
			default: throw new Error("constant");
		}
	}
	/** Ensure extensions are only requested once */
	getExtension(name) {
		getWebGLExtension(this.gl, name, this.extensions);
		return this.extensions;
	}
	/**
	* Storing data on a special field on WebGLObjects makes that data visible in SPECTOR chrome debug extension
	* luma.gl ids and props can be inspected
	*/
	_setWebGLDebugMetadata(handle, resource, options) {
		handle.luma = resource;
		handle.__SPECTOR_Metadata = {
			props: options.spector,
			id: options.spector["id"]
		};
	}
};
/** Set constant float array attribute */
function setConstantFloatArray(device, location, array) {
	switch (array.length) {
		case 1:
			device.gl.vertexAttrib1fv(location, array);
			break;
		case 2:
			device.gl.vertexAttrib2fv(location, array);
			break;
		case 3:
			device.gl.vertexAttrib3fv(location, array);
			break;
		case 4:
			device.gl.vertexAttrib4fv(location, array);
			break;
		default:
	}
}
/** Set constant signed int array attribute */
function setConstantIntArray(device, location, array) {
	device.gl.vertexAttribI4iv(location, array);
}
/** Set constant unsigned int array attribute */
function setConstantUintArray(device, location, array) {
	device.gl.vertexAttribI4uiv(location, array);
}
/**
* Compares contents of two typed arrays
* @todo max length?
*/
function compareConstantArrayValues(v1, v2) {
	if (!v1 || !v2 || v1.length !== v2.length || v1.constructor !== v2.constructor) return false;
	for (let i = 0; i < v1.length; ++i) if (v1[i] !== v2[i]) return false;
	return true;
}
//#endregion
export { getTypedArrayConstructor as a, resolveVariableShaderTypeAlias as c, Shader as d, TextureView as f, alignTo as i, normalizeBindingsByGroup as l, webgl_device_exports as n, getAttributeInfosFromLayouts as o, getScratchArrayBuffer as r, getVariableShaderTypeInfo as s, WebGLDevice as t, RenderPipeline as u };

//# sourceMappingURL=webgl-device-DmZ5B3dw.js.map