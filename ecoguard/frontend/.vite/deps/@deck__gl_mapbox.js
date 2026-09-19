import { A as lngLatToWorld$1, At as assert, B as EVENT_HANDLERS, Ct as defaultLogger, E as MAX_LATITUDE, Et as Stats, G as geometry_default, H as RECOGNIZERS, I as project_default, M as unitsPerMeter, N as worldToLngLat, O as altitudeToFovy, Ot as isBrowser$1, R as getShaderCoordinateSystem, S as mod, St as register, Tt as registerLoaders, V as PROJECTION_MODE, W as EventManager, Y as Device, _ as LIFECYCLE, _t as equals, a as loadSpectorJS, b as Viewport, c as Transition, ct as Matrix4, d as flatten, dt as Vector3, ft as len, gt as clamp, ht as sub, j as pixelsToWorld, k as fovyToAltitude, kt as isBrowser, l as deepEqual, lt as scale, mt as sqrLen, ot as log, pt as lerp, q as Texture, r as DEFAULT_SPECTOR_PROPS, rt as Buffer, s as assert$1, st as lumaStats, t as loadWebGLDeveloperTools, ut as transformMat4, vt as lerp$1, w as typed_array_manager_default, wt as load, xt as debug, y as WebMercatorViewport, yt as ShaderAssembler, z as memoize } from "./webgl-developer-tools-CC6tnIIX.js";
//#region node_modules/@loaders.gl/images/dist/lib/utils/version.js
var VERSION$1 = "4.4.5";
//#endregion
//#region node_modules/@loaders.gl/images/dist/lib/category-api/image-type.js
var parseImageNode = globalThis.loaders?.parseImageNode;
var IMAGE_SUPPORTED = typeof Image !== "undefined";
var IMAGE_BITMAP_SUPPORTED = typeof ImageBitmap !== "undefined";
var DATA_SUPPORTED = isBrowser ? true : Boolean(parseImageNode);
/**
* Checks if a loaders.gl image type is supported
* @param type image type string
*/
function isImageTypeSupported(type) {
	switch (type) {
		case "auto": return IMAGE_BITMAP_SUPPORTED || IMAGE_SUPPORTED || DATA_SUPPORTED;
		case "imagebitmap": return IMAGE_BITMAP_SUPPORTED;
		case "image": return IMAGE_SUPPORTED;
		case "data": return DATA_SUPPORTED;
		default: throw new Error(`@loaders.gl/images: image ${type} not supported in this environment`);
	}
}
/**
* Returns the "most performant" supported image type on this platform
* @returns image type string
*/
function getDefaultImageType() {
	if (IMAGE_BITMAP_SUPPORTED) return "imagebitmap";
	if (IMAGE_SUPPORTED) return "image";
	if (DATA_SUPPORTED) return "data";
	throw new Error("Install '@loaders.gl/polyfills' to parse images under Node.js");
}
//#endregion
//#region node_modules/@loaders.gl/images/dist/lib/category-api/parsed-image-api.js
function getImageType(image) {
	const format = getImageTypeOrNull(image);
	if (!format) throw new Error("Not an image");
	return format;
}
function getImageData(image) {
	switch (getImageType(image)) {
		case "data": return image;
		case "image":
		case "imagebitmap":
			const canvas = document.createElement("canvas");
			const context = canvas.getContext("2d");
			if (!context) throw new Error("getImageData");
			canvas.width = image.width;
			canvas.height = image.height;
			context.drawImage(image, 0, 0);
			return context.getImageData(0, 0, image.width, image.height);
		default: throw new Error("getImageData");
	}
}
function getImageTypeOrNull(image) {
	if (typeof ImageBitmap !== "undefined" && image instanceof ImageBitmap) return "imagebitmap";
	if (typeof Image !== "undefined" && image instanceof Image) return "image";
	if (image && typeof image === "object" && image.data && image.width && image.height) return "data";
	return null;
}
//#endregion
//#region node_modules/@loaders.gl/images/dist/lib/parsers/svg-utils.js
var SVG_DATA_URL_PATTERN = /^data:image\/svg\+xml/;
var SVG_URL_PATTERN = /\.svg((\?|#).*)?$/;
function isSVG(url) {
	return url && (SVG_DATA_URL_PATTERN.test(url) || SVG_URL_PATTERN.test(url));
}
function getBlobOrSVGDataUrl(arrayBuffer, url) {
	if (isSVG(url)) {
		let xmlText = new TextDecoder().decode(arrayBuffer);
		try {
			if (typeof unescape === "function" && typeof encodeURIComponent === "function") xmlText = unescape(encodeURIComponent(xmlText));
		} catch (error) {
			throw new Error(error.message);
		}
		return `data:image/svg+xml;base64,${btoa(xmlText)}`;
	}
	return getBlob(arrayBuffer, url);
}
function getBlob(arrayBuffer, url) {
	if (isSVG(url)) throw new Error("SVG cannot be parsed directly to imagebitmap");
	return new Blob([new Uint8Array(arrayBuffer)]);
}
//#endregion
//#region node_modules/@loaders.gl/images/dist/lib/parsers/parse-to-image.js
async function parseToImage(arrayBuffer, options, url) {
	const blobOrDataUrl = getBlobOrSVGDataUrl(arrayBuffer, url);
	const URL = self.URL || self.webkitURL;
	const objectUrl = typeof blobOrDataUrl !== "string" && URL.createObjectURL(blobOrDataUrl);
	try {
		return await loadToImage(objectUrl || blobOrDataUrl, options);
	} finally {
		if (objectUrl) URL.revokeObjectURL(objectUrl);
	}
}
async function loadToImage(url, options) {
	const image = new Image();
	image.src = url;
	if (options.image && options.image.decode && image.decode) {
		await image.decode();
		return image;
	}
	return await new Promise((resolve, reject) => {
		try {
			image.onload = () => resolve(image);
			image.onerror = (error) => {
				const message = error instanceof Error ? error.message : "error";
				reject(new Error(message));
			};
		} catch (error) {
			reject(error);
		}
	});
}
//#endregion
//#region node_modules/@loaders.gl/images/dist/lib/parsers/parse-to-image-bitmap.js
var imagebitmapOptionsSupported = true;
/**
* Asynchronously parses an array buffer into an ImageBitmap - this contains the decoded data
* ImageBitmaps are supported on worker threads, but not supported on Edge, IE11 and Safari
* https://developer.mozilla.org/en-US/docs/Web/API/ImageBitmap#Browser_compatibility
*
* TODO - createImageBitmap supports source rect (5 param overload), pass through?
*/
async function parseToImageBitmap(arrayBuffer, options, url) {
	let blob;
	if (isSVG(url)) blob = await parseToImage(arrayBuffer, options, url);
	else blob = getBlob(arrayBuffer, url);
	const imagebitmapOptions = options && options.imagebitmap;
	return await safeCreateImageBitmap(blob, imagebitmapOptions);
}
/**
* Safely creates an imageBitmap with options
* *
* Firefox crashes if imagebitmapOptions is supplied
* Avoid supplying if not provided or supported, remember if not supported
*/
async function safeCreateImageBitmap(blob, imagebitmapOptions = null) {
	if (isEmptyObject(imagebitmapOptions) || !imagebitmapOptionsSupported) imagebitmapOptions = null;
	if (imagebitmapOptions) try {
		return await createImageBitmap(blob, imagebitmapOptions);
	} catch (error) {
		console.warn(error);
		imagebitmapOptionsSupported = false;
	}
	return await createImageBitmap(blob);
}
function isEmptyObject(object) {
	if (!object) return true;
	for (const key in object) if (Object.prototype.hasOwnProperty.call(object, key)) return false;
	return true;
}
//#endregion
//#region node_modules/@loaders.gl/images/dist/lib/category-api/parse-isobmff-binary.js
/**
* Tests if a buffer is in ISO base media file format (ISOBMFF) @see https://en.wikipedia.org/wiki/ISO_base_media_file_format
* (ISOBMFF is a media container standard based on the Apple QuickTime container format)
*/
function getISOBMFFMediaType(buffer) {
	if (!checkString(buffer, "ftyp", 4)) return null;
	if ((buffer[8] & 96) === 0) return null;
	return decodeMajorBrand(buffer);
}
/**
* brands explained @see https://github.com/strukturag/libheif/issues/83
* code adapted from @see https://github.com/sindresorhus/file-type/blob/main/core.js#L489-L492
*/
function decodeMajorBrand(buffer) {
	switch (getUTF8String(buffer, 8, 12).replace("\0", " ").trim()) {
		case "avif":
		case "avis": return {
			extension: "avif",
			mimeType: "image/avif"
		};
		default: return null;
	}
}
/** Interpret a chunk of bytes as a UTF8 string */
function getUTF8String(array, start, end) {
	return String.fromCharCode(...array.slice(start, end));
}
function stringToBytes(string) {
	return [...string].map((character) => character.charCodeAt(0));
}
function checkString(buffer, header, offset = 0) {
	const headerBytes = stringToBytes(header);
	for (let i = 0; i < headerBytes.length; ++i) if (headerBytes[i] !== buffer[i + offset]) return false;
	return true;
}
//#endregion
//#region node_modules/@loaders.gl/images/dist/lib/category-api/binary-image-api.js
var BIG_ENDIAN = false;
var LITTLE_ENDIAN = true;
/**
* Extracts `{mimeType, width and height}` from a memory buffer containing a known image format
* Currently supports `image/png`, `image/jpeg`, `image/bmp` and `image/gif`.
* @param binaryData: DataView | ArrayBuffer image file memory to parse
* @returns metadata or null if memory is not a valid image file format layout.
*/
function getBinaryImageMetadata(binaryData) {
	const dataView = toDataView(binaryData);
	return getPngMetadata(dataView) || getJpegMetadata(dataView) || getGifMetadata(dataView) || getBmpMetadata(dataView) || getISOBMFFMetadata(dataView);
}
function getISOBMFFMetadata(binaryData) {
	const mediaType = getISOBMFFMediaType(new Uint8Array(binaryData instanceof DataView ? binaryData.buffer : binaryData));
	if (!mediaType) return null;
	return {
		mimeType: mediaType.mimeType,
		width: 0,
		height: 0
	};
}
function getPngMetadata(binaryData) {
	const dataView = toDataView(binaryData);
	if (!(dataView.byteLength >= 24 && dataView.getUint32(0, BIG_ENDIAN) === 2303741511)) return null;
	return {
		mimeType: "image/png",
		width: dataView.getUint32(16, BIG_ENDIAN),
		height: dataView.getUint32(20, BIG_ENDIAN)
	};
}
function getGifMetadata(binaryData) {
	const dataView = toDataView(binaryData);
	if (!(dataView.byteLength >= 10 && dataView.getUint32(0, BIG_ENDIAN) === 1195984440)) return null;
	return {
		mimeType: "image/gif",
		width: dataView.getUint16(6, LITTLE_ENDIAN),
		height: dataView.getUint16(8, LITTLE_ENDIAN)
	};
}
function getBmpMetadata(binaryData) {
	const dataView = toDataView(binaryData);
	if (!(dataView.byteLength >= 14 && dataView.getUint16(0, BIG_ENDIAN) === 16973 && dataView.getUint32(2, LITTLE_ENDIAN) === dataView.byteLength)) return null;
	return {
		mimeType: "image/bmp",
		width: dataView.getUint32(18, LITTLE_ENDIAN),
		height: dataView.getUint32(22, LITTLE_ENDIAN)
	};
}
function getJpegMetadata(binaryData) {
	const dataView = toDataView(binaryData);
	if (!(dataView.byteLength >= 3 && dataView.getUint16(0, BIG_ENDIAN) === 65496 && dataView.getUint8(2) === 255)) return null;
	const { tableMarkers, sofMarkers } = getJpegMarkers();
	let i = 2;
	while (i + 9 < dataView.byteLength) {
		const marker = dataView.getUint16(i, BIG_ENDIAN);
		if (sofMarkers.has(marker)) return {
			mimeType: "image/jpeg",
			height: dataView.getUint16(i + 5, BIG_ENDIAN),
			width: dataView.getUint16(i + 7, BIG_ENDIAN)
		};
		if (!tableMarkers.has(marker)) return null;
		i += 2;
		i += dataView.getUint16(i, BIG_ENDIAN);
	}
	return null;
}
function getJpegMarkers() {
	const tableMarkers = new Set([
		65499,
		65476,
		65484,
		65501,
		65534
	]);
	for (let i = 65504; i < 65520; ++i) tableMarkers.add(i);
	return {
		tableMarkers,
		sofMarkers: new Set([
			65472,
			65473,
			65474,
			65475,
			65477,
			65478,
			65479,
			65481,
			65482,
			65483,
			65485,
			65486,
			65487,
			65502
		])
	};
}
function toDataView(data) {
	if (data instanceof DataView) return data;
	if (ArrayBuffer.isView(data)) return new DataView(data.buffer);
	if (data instanceof ArrayBuffer) return new DataView(data);
	throw new Error("toDataView");
}
//#endregion
//#region node_modules/@loaders.gl/images/dist/lib/parsers/parse-to-node-image.js
async function parseToNodeImage(arrayBuffer, options) {
	const { mimeType } = getBinaryImageMetadata(arrayBuffer) || {};
	const parseImageNode = globalThis.loaders?.parseImageNode;
	assert(parseImageNode);
	return await parseImageNode(arrayBuffer, mimeType);
}
//#endregion
//#region node_modules/@loaders.gl/images/dist/lib/parsers/parse-image.js
async function parseImage(arrayBuffer, options, context) {
	options = options || {};
	const imageType = (options.image || {}).type || "auto";
	const { url } = context || {};
	const loadType = getLoadableImageType(imageType);
	let image;
	switch (loadType) {
		case "imagebitmap":
			image = await parseToImageBitmap(arrayBuffer, options, url);
			break;
		case "image":
			image = await parseToImage(arrayBuffer, options, url);
			break;
		case "data":
			image = await parseToNodeImage(arrayBuffer, options);
			break;
		default: assert(false);
	}
	if (imageType === "data") image = getImageData(image);
	return image;
}
function getLoadableImageType(type) {
	switch (type) {
		case "auto":
		case "data": return getDefaultImageType();
		default:
			isImageTypeSupported(type);
			return type;
	}
}
/**
* Loads a platform-specific image type
* Note: This type can be used as input data to WebGL texture creation
*/
var ImageLoader = {
	dataType: null,
	batchType: null,
	id: "image",
	module: "images",
	name: "Images",
	version: VERSION$1,
	mimeTypes: [
		"image/png",
		"image/jpeg",
		"image/gif",
		"image/webp",
		"image/avif",
		"image/bmp",
		"image/vnd.microsoft.icon",
		"image/svg+xml"
	],
	extensions: [
		"png",
		"jpg",
		"jpeg",
		"gif",
		"webp",
		"bmp",
		"ico",
		"svg",
		"avif"
	],
	parse: parseImage,
	tests: [(arrayBuffer) => Boolean(getBinaryImageMetadata(new DataView(arrayBuffer)))],
	options: { image: {
		type: "auto",
		decode: true
	} }
};
//#endregion
//#region node_modules/@deck.gl/core/dist/utils/json-loader.js
function isJSON(text) {
	const firstChar = text[0];
	const lastChar = text[text.length - 1];
	return firstChar === "{" && lastChar === "}" || firstChar === "[" && lastChar === "]";
}
var json_loader_default = {
	dataType: null,
	batchType: null,
	id: "JSON",
	name: "JSON",
	module: "",
	version: "",
	options: {},
	extensions: ["json", "geojson"],
	mimeTypes: ["application/json", "application/geo+json"],
	testText: isJSON,
	parseTextSync: JSON.parse
};
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/init.js
function checkVersion() {
	const version = "9.3.10";
	const existingVersion = globalThis.deck && globalThis.deck.VERSION;
	if (existingVersion && existingVersion !== version) throw new Error(`deck.gl - multiple versions detected: ${existingVersion} vs ${version}`);
	if (!existingVersion) {
		defaultLogger.log(1, `deck.gl ${version}`)();
		globalThis.deck = {
			...globalThis.deck,
			VERSION: version,
			version,
			log: defaultLogger,
			_registerLoggers: register
		};
		registerLoaders([json_loader_default, [ImageLoader, { imagebitmap: { premultiplyAlpha: "none" } }]]);
	}
	return version;
}
var VERSION = checkVersion();
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/luma.js
var STARTUP_MESSAGE = "set luma.log.level=1 (or higher) to trace rendering";
var ERROR_MESSAGE = "No matching device found. Ensure `@luma.gl/webgl` and/or `@luma.gl/webgpu` modules are imported.";
/**
* Entry point to the luma.gl GPU abstraction
* Register WebGPU and/or WebGL adapters (controls application bundle size)
* Run-time selection of the first available Device
*/
var luma = new class Luma {
	static defaultProps = {
		...Device.defaultProps,
		type: "best-available",
		adapters: void 0,
		waitForPageLoad: true
	};
	/** Global stats for all devices */
	stats = lumaStats;
	/**
	* Global log
	*
	* Assign luma.log.level in console to control logging: \
	* 0: none, 1: minimal, 2: verbose, 3: attribute/uniforms, 4: gl logs
	* luma.log.break[], set to gl funcs, luma.log.profile[] set to model names`;
	*/
	log = log;
	/** Version of luma.gl */
	VERSION = "9.3.6";
	spector;
	preregisteredAdapters = /* @__PURE__ */ new Map();
	constructor() {
		if (globalThis.luma) {
			if (globalThis.luma.VERSION !== this.VERSION) {
				log.error(`Found luma.gl ${globalThis.luma.VERSION} while initialzing ${this.VERSION}`)();
				log.error(`'yarn why @luma.gl/core' can help identify the source of the conflict`)();
				throw new Error(`luma.gl - multiple versions detected: see console log`);
			}
			log.error("This version of luma.gl has already been initialized")();
		}
		log.log(1, `${this.VERSION} - ${STARTUP_MESSAGE}`)();
		globalThis.luma = this;
	}
	/** Creates a device. Asynchronously. */
	async createDevice(props_ = {}) {
		const props = {
			...Luma.defaultProps,
			...props_
		};
		const adapter = this.selectAdapter(props.type, props.adapters);
		if (!adapter) throw new Error(ERROR_MESSAGE);
		if (props.waitForPageLoad) await adapter.pageLoaded;
		return await adapter.create(props);
	}
	/**
	* Attach to an existing GPU API handle (WebGL2RenderingContext or GPUDevice).
	* @param handle Externally created WebGL context or WebGPU device
	*/
	async attachDevice(handle, props) {
		const type = this._getTypeFromHandle(handle, props.adapters);
		const adapter = type && this.selectAdapter(type, props.adapters);
		if (!adapter) throw new Error(ERROR_MESSAGE);
		return await adapter?.attach?.(handle, props);
	}
	/**
	* Global adapter registration.
	* @deprecated Use props.adapters instead
	*/
	registerAdapters(adapters) {
		for (const deviceClass of adapters) this.preregisteredAdapters.set(deviceClass.type, deviceClass);
	}
	/** Get type strings for supported Devices */
	getSupportedAdapters(adapters = []) {
		const adapterMap = this._getAdapterMap(adapters);
		return Array.from(adapterMap).map(([, adapter]) => adapter).filter((adapter) => adapter.isSupported?.()).map((adapter) => adapter.type);
	}
	/** Get type strings for best available Device */
	getBestAvailableAdapterType(adapters = []) {
		const KNOWN_ADAPTERS = [
			"webgpu",
			"webgl",
			"null"
		];
		const adapterMap = this._getAdapterMap(adapters);
		for (const type of KNOWN_ADAPTERS) if (adapterMap.get(type)?.isSupported?.()) return type;
		return null;
	}
	/** Select adapter of type from registered adapters */
	selectAdapter(type, adapters = []) {
		let selectedType = type;
		if (type === "best-available") selectedType = this.getBestAvailableAdapterType(adapters);
		const adapterMap = this._getAdapterMap(adapters);
		return selectedType && adapterMap.get(selectedType) || null;
	}
	/**
	* Override `HTMLCanvasContext.getCanvas()` to always create WebGL2 contexts with additional WebGL1 compatibility.
	* Useful when attaching luma to a context from an external library does not support creating WebGL2 contexts.
	*/
	enforceWebGL2(enforce = true, adapters = []) {
		const webgl2Adapter = this._getAdapterMap(adapters).get("webgl");
		if (!webgl2Adapter) log.warn("enforceWebGL2: webgl adapter not found")();
		webgl2Adapter?.enforceWebGL2?.(enforce);
	}
	/** @deprecated */
	setDefaultDeviceProps(props) {
		Object.assign(Luma.defaultProps, props);
	}
	/** Convert a list of adapters to a map */
	_getAdapterMap(adapters = []) {
		const map = new Map(this.preregisteredAdapters);
		for (const adapter of adapters) map.set(adapter.type, adapter);
		return map;
	}
	/** Get type of a handle (for attachDevice) */
	_getTypeFromHandle(handle, adapters = []) {
		if (handle instanceof WebGL2RenderingContext) return "webgl";
		if (typeof GPUDevice !== "undefined" && handle instanceof GPUDevice) return "webgpu";
		if (handle?.queue) return "webgpu";
		if (handle === null) return "null";
		if (handle instanceof WebGLRenderingContext) log.warn("WebGL1 is not supported", handle)();
		else log.warn("Unknown handle type", handle)();
		return null;
	}
}();
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/adapter.js
/**
* Create and attach devices for a specific backend.
*/
var Adapter = class {
	/**
	* Page load promise
	* Resolves when the DOM is loaded.
	* @note Since are be limitations on number of `load` event listeners,
	* it is recommended avoid calling this accessor until actually needed.
	* I.e. we don't call it unless you know that you will be looking up a string in the DOM.
	*/
	get pageLoaded() {
		return getPageLoadPromise();
	}
};
var isPage = isBrowser$1() && typeof document !== "undefined";
var isPageLoaded = () => isPage && document.readyState === "complete";
var pageLoadPromise = null;
/** Returns a promise that resolves when the page is loaded */
function getPageLoadPromise() {
	if (!pageLoadPromise) if (isPageLoaded() || typeof window === "undefined") pageLoadPromise = Promise.resolve();
	else pageLoadPromise = new Promise((resolve) => window.addEventListener("load", () => resolve()));
	return pageLoadPromise;
}
//#endregion
//#region node_modules/@deck.gl/core/dist/shaderlib/misc/layer-uniforms.js
var uniformBlockWGSL = `\
struct LayerUniforms {
  opacity: f32,
};

@group(0) @binding(auto)
var<uniform> layer: LayerUniforms;
`;
var uniformBlock$1 = `\
layout(std140) uniform layerUniforms {
  uniform float opacity;
} layer;
`;
var layerUniforms = {
	name: "layer",
	source: uniformBlockWGSL,
	vs: uniformBlock$1,
	fs: uniformBlock$1,
	getUniforms: (props) => {
		return { opacity: Math.pow(props.opacity, 1 / 2.2) };
	},
	uniformTypes: { opacity: "f32" }
};
//#endregion
//#region node_modules/@deck.gl/core/dist/shaderlib/shadow/shadow.js
var uniformBlock = `
layout(std140) uniform shadowUniforms {
  bool drawShadowMap;
  bool useShadowMap;
  vec4 color;
  highp int lightId;
  float lightCount;
  mat4 viewProjectionMatrix0;
  mat4 viewProjectionMatrix1;
  vec4 projectCenter0;
  vec4 projectCenter1;
} shadow;
`;
var vs = `
${uniformBlock}

const int max_lights = 2;

out vec3 shadow_vPosition[max_lights];

vec4 shadow_setVertexPosition(vec4 position_commonspace) {
  mat4 viewProjectionMatrices[max_lights];
  viewProjectionMatrices[0] = shadow.viewProjectionMatrix0;
  viewProjectionMatrices[1] = shadow.viewProjectionMatrix1;
  vec4 projectCenters[max_lights];
  projectCenters[0] = shadow.projectCenter0;
  projectCenters[1] = shadow.projectCenter1;

  if (shadow.drawShadowMap) {
    return project_common_position_to_clipspace(position_commonspace, viewProjectionMatrices[shadow.lightId], projectCenters[shadow.lightId]);
  }
  if (shadow.useShadowMap) {
    for (int i = 0; i < max_lights; i++) {
      if(i < int(shadow.lightCount)) {
        vec4 shadowMap_position = project_common_position_to_clipspace(position_commonspace, viewProjectionMatrices[i], projectCenters[i]);
        shadow_vPosition[i] = (shadowMap_position.xyz / shadowMap_position.w + 1.0) / 2.0;
      }
    }
  }
  return gl_Position;
}

`;
var fs = `
${uniformBlock}

const int max_lights = 2;
uniform sampler2D shadow_uShadowMap0;
uniform sampler2D shadow_uShadowMap1;

in vec3 shadow_vPosition[max_lights];

const vec4 bitPackShift = vec4(1.0, 255.0, 65025.0, 16581375.0);
const vec4 bitUnpackShift = 1.0 / bitPackShift;
const vec4 bitMask = vec4(1.0 / 255.0, 1.0 / 255.0, 1.0 / 255.0,  0.0);

float shadow_getShadowWeight(vec3 position, sampler2D shadowMap) {
  vec4 rgbaDepth = texture(shadowMap, position.xy);

  float z = dot(rgbaDepth, bitUnpackShift);
  return smoothstep(0.001, 0.01, position.z - z);
}

vec4 shadow_filterShadowColor(vec4 color) {
  if (shadow.drawShadowMap) {
    vec4 rgbaDepth = fract(gl_FragCoord.z * bitPackShift);
    rgbaDepth -= rgbaDepth.gbaa * bitMask;
    return rgbaDepth;
  }
  if (shadow.useShadowMap) {
    float shadowAlpha = 0.0;
    shadowAlpha += shadow_getShadowWeight(shadow_vPosition[0], shadow_uShadowMap0);
    if(shadow.lightCount > 1.0) {
      shadowAlpha += shadow_getShadowWeight(shadow_vPosition[1], shadow_uShadowMap1);
    }
    shadowAlpha *= shadow.color.a / shadow.lightCount;
    float blendedAlpha = shadowAlpha + color.a * (1.0 - shadowAlpha);

    return vec4(
      mix(color.rgb, shadow.color.rgb, shadowAlpha / blendedAlpha),
      blendedAlpha
    );
  }
  return color;
}

`;
var getMemoizedViewportCenterPosition = memoize(getViewportCenterPosition);
var getMemoizedViewProjectionMatrices = memoize(getViewProjectionMatrices);
var DEFAULT_SHADOW_COLOR$1 = [
	0,
	0,
	0,
	1
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
function screenToCommonSpace(xyz, pixelUnprojectionMatrix) {
	const [x, y, z] = xyz;
	const coord = pixelsToWorld([
		x,
		y,
		z
	], pixelUnprojectionMatrix);
	if (Number.isFinite(z)) return coord;
	return [
		coord[0],
		coord[1],
		0
	];
}
function getViewportCenterPosition({ viewport, center }) {
	return new Matrix4(viewport.viewProjectionMatrix).invert().transform(center);
}
function getViewProjectionMatrices({ viewport, shadowMatrices }) {
	const projectionMatrices = [];
	const pixelUnprojectionMatrix = viewport.pixelUnprojectionMatrix;
	const farZ = viewport.isGeospatial ? void 0 : 1;
	const corners = [
		[
			0,
			0,
			farZ
		],
		[
			viewport.width,
			0,
			farZ
		],
		[
			0,
			viewport.height,
			farZ
		],
		[
			viewport.width,
			viewport.height,
			farZ
		],
		[
			0,
			0,
			-1
		],
		[
			viewport.width,
			0,
			-1
		],
		[
			0,
			viewport.height,
			-1
		],
		[
			viewport.width,
			viewport.height,
			-1
		]
	].map((pixel) => screenToCommonSpace(pixel, pixelUnprojectionMatrix));
	for (const shadowMatrix of shadowMatrices) {
		const viewMatrix = shadowMatrix.clone().translate(new Vector3(viewport.center).negate());
		const positions = corners.map((corner) => viewMatrix.transform(corner));
		const projectionMatrix = new Matrix4().ortho({
			left: Math.min(...positions.map((position) => position[0])),
			right: Math.max(...positions.map((position) => position[0])),
			bottom: Math.min(...positions.map((position) => position[1])),
			top: Math.max(...positions.map((position) => position[1])),
			near: Math.min(...positions.map((position) => -position[2])),
			far: Math.max(...positions.map((position) => -position[2]))
		});
		projectionMatrices.push(projectionMatrix.multiplyRight(shadowMatrix));
	}
	return projectionMatrices;
}
function createShadowUniforms(opts) {
	const { shadowEnabled = true, project: projectProps } = opts;
	if (!shadowEnabled || !projectProps || !opts.shadowMatrices || !opts.shadowMatrices.length) return {
		drawShadowMap: false,
		useShadowMap: false,
		shadow_uShadowMap0: opts.dummyShadowMap,
		shadow_uShadowMap1: opts.dummyShadowMap
	};
	const projectUniforms = project_default.getUniforms(projectProps);
	const center = getMemoizedViewportCenterPosition({
		viewport: projectProps.viewport,
		center: projectUniforms.center
	});
	const projectCenters = [];
	const viewProjectionMatrices = getMemoizedViewProjectionMatrices({
		shadowMatrices: opts.shadowMatrices,
		viewport: projectProps.viewport
	}).slice();
	for (let i = 0; i < opts.shadowMatrices.length; i++) {
		const viewProjectionMatrix = viewProjectionMatrices[i];
		const viewProjectionMatrixCentered = viewProjectionMatrix.clone().translate(new Vector3(projectProps.viewport.center).negate());
		if (projectUniforms.coordinateSystem === getShaderCoordinateSystem("lnglat") && projectUniforms.projectionMode === PROJECTION_MODE.WEB_MERCATOR) {
			viewProjectionMatrices[i] = viewProjectionMatrixCentered;
			projectCenters[i] = center;
		} else {
			viewProjectionMatrices[i] = viewProjectionMatrix.clone().multiplyRight(VECTOR_TO_POINT_MATRIX);
			projectCenters[i] = viewProjectionMatrixCentered.transform(center);
		}
	}
	const uniforms = {
		drawShadowMap: Boolean(opts.drawToShadowMap),
		useShadowMap: opts.shadowMaps ? opts.shadowMaps.length > 0 : false,
		color: opts.shadowColor || DEFAULT_SHADOW_COLOR$1,
		lightId: opts.shadowLightId || 0,
		lightCount: opts.shadowMatrices.length,
		shadow_uShadowMap0: opts.dummyShadowMap,
		shadow_uShadowMap1: opts.dummyShadowMap
	};
	for (let i = 0; i < viewProjectionMatrices.length; i++) {
		uniforms[`viewProjectionMatrix${i}`] = viewProjectionMatrices[i];
		uniforms[`projectCenter${i}`] = projectCenters[i];
	}
	for (let i = 0; i < 2; i++) uniforms[`shadow_uShadowMap${i}`] = opts.shadowMaps && opts.shadowMaps[i] || opts.dummyShadowMap;
	return uniforms;
}
var shadow_default = {
	name: "shadow",
	dependencies: [project_default],
	vs,
	fs,
	inject: {
		"vs:DECKGL_FILTER_GL_POSITION": `
    position = shadow_setVertexPosition(geometry.position);
    `,
		"fs:DECKGL_FILTER_COLOR": `
    color = shadow_filterShadowColor(color);
    `
	},
	getUniforms: createShadowUniforms,
	uniformTypes: {
		drawShadowMap: "f32",
		useShadowMap: "f32",
		color: "vec4<f32>",
		lightId: "i32",
		lightCount: "f32",
		viewProjectionMatrix0: "mat4x4<f32>",
		viewProjectionMatrix1: "mat4x4<f32>",
		projectCenter0: "vec4<f32>",
		projectCenter1: "vec4<f32>"
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/shaderlib/index.js
var DEFAULT_MODULES = [geometry_default];
var SHADER_HOOKS_GLSL = [
	"vs:DECKGL_FILTER_SIZE(inout vec3 size, VertexGeometry geometry)",
	"vs:DECKGL_FILTER_GL_POSITION(inout vec4 position, VertexGeometry geometry)",
	"vs:DECKGL_FILTER_COLOR(inout vec4 color, VertexGeometry geometry)",
	"fs:DECKGL_FILTER_COLOR(inout vec4 color, FragmentGeometry geometry)"
];
var SHADER_HOOKS_WGSL = [];
function getShaderAssembler(language) {
	const shaderAssembler = ShaderAssembler.getDefaultShaderAssembler();
	for (const shaderModule of DEFAULT_MODULES) shaderAssembler.addDefaultModule(shaderModule);
	shaderAssembler._hookFunctions.length = 0;
	const shaderHooks = language === "glsl" ? SHADER_HOOKS_GLSL : SHADER_HOOKS_WGSL;
	for (const shaderHook of shaderHooks) shaderAssembler.addShaderHook(shaderHook);
	return shaderAssembler;
}
//#endregion
//#region node_modules/@deck.gl/core/dist/effects/lighting/ambient-light.js
var DEFAULT_LIGHT_COLOR$1 = [
	255,
	255,
	255
];
var DEFAULT_LIGHT_INTENSITY$1 = 1;
var idCount$1 = 0;
var AmbientLight = class {
	constructor(props = {}) {
		this.type = "ambient";
		const { color = DEFAULT_LIGHT_COLOR$1 } = props;
		const { intensity = DEFAULT_LIGHT_INTENSITY$1 } = props;
		this.id = props.id || `ambient-${idCount$1++}`;
		this.color = color;
		this.intensity = intensity;
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/effects/lighting/directional-light.js
var DEFAULT_LIGHT_COLOR = [
	255,
	255,
	255
];
var DEFAULT_LIGHT_INTENSITY = 1;
var DEFAULT_LIGHT_DIRECTION = [
	0,
	0,
	-1
];
var idCount = 0;
var DirectionalLight = class {
	constructor(props = {}) {
		this.type = "directional";
		const { color = DEFAULT_LIGHT_COLOR } = props;
		const { intensity = DEFAULT_LIGHT_INTENSITY } = props;
		const { direction = DEFAULT_LIGHT_DIRECTION } = props;
		const { _shadow = false } = props;
		this.id = props.id || `directional-${idCount++}`;
		this.color = color;
		this.intensity = intensity;
		this.type = "directional";
		this.direction = new Vector3(direction).normalize().toArray();
		this.shadow = _shadow;
	}
	getProjectedLight(opts) {
		return this;
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/passes/pass.js
/**
* Base class for passes
* @todo v9 - should the luma.gl RenderPass be owned by this class?
* Currently owned by subclasses
*/
var Pass = class {
	/** Create a new Pass instance */
	constructor(device, props = { id: "pass" }) {
		const { id } = props;
		this.id = id;
		this.device = device;
		this.props = { ...props };
	}
	setProps(props) {
		Object.assign(this.props, props);
	}
	render(params) {}
	cleanup() {}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/passes/layers-pass.js
var WEBGPU_DEFAULT_DRAW_PARAMETERS = {
	depthWriteEnabled: true,
	depthCompare: "less-equal",
	blendColorOperation: "add",
	blendColorSrcFactor: "src-alpha",
	blendColorDstFactor: "one",
	blendAlphaOperation: "add",
	blendAlphaSrcFactor: "one-minus-dst-alpha",
	blendAlphaDstFactor: "one"
};
/** A Pass that renders all layers */
var LayersPass = class extends Pass {
	constructor() {
		super(...arguments);
		this._lastRenderIndex = -1;
	}
	render(options) {
		this._render(options);
	}
	_render(options) {
		const canvasContext = this.device.canvasContext;
		const framebuffer = options.target ?? canvasContext.getCurrentFramebuffer();
		const [width, height] = canvasContext.getDrawingBufferSize();
		const clearCanvas = options.clearCanvas ?? true;
		const clearColor = options.clearColor ?? (clearCanvas ? [
			0,
			0,
			0,
			0
		] : false);
		const clearDepth = clearCanvas ? 1 : false;
		const clearStencil = clearCanvas ? 0 : false;
		const colorMask = options.colorMask ?? 15;
		const parameters = { viewport: [
			0,
			0,
			width,
			height
		] };
		if (options.colorMask) parameters.colorMask = colorMask;
		if (options.scissorRect) parameters.scissorRect = options.scissorRect;
		const renderPass = this.device.beginRenderPass({
			framebuffer,
			parameters,
			clearColor,
			clearDepth,
			clearStencil
		});
		try {
			return this._drawLayers(renderPass, options);
		} finally {
			renderPass.end();
			this.device.submit();
		}
	}
	/** Draw a list of layers in a list of viewports */
	_drawLayers(renderPass, options) {
		const { target, shaderModuleProps, viewports, views, onViewportActive, clearStack = true } = options;
		options.pass = options.pass || "unknown";
		if (clearStack) this._lastRenderIndex = -1;
		const renderStats = [];
		for (const viewport of viewports) {
			const view = views && views[viewport.id];
			onViewportActive?.(viewport);
			const drawLayerParams = this._getDrawLayerParams(viewport, options);
			const subViewports = viewport.subViewports || [viewport];
			for (const subViewport of subViewports) {
				const stats = this._drawLayersInViewport(renderPass, {
					target,
					shaderModuleProps,
					viewport: subViewport,
					view,
					pass: options.pass,
					layers: options.layers,
					isPicking: options.isPicking
				}, drawLayerParams);
				renderStats.push(stats);
			}
		}
		return renderStats;
	}
	_getDrawLayerParams(viewport, { layers, pass, isPicking = false, layerFilter, cullRect, views, effects, shaderModuleProps }, evaluateShouldDrawOnly = false) {
		const drawLayerParams = [];
		const indexResolver = layerIndexResolver(this._lastRenderIndex + 1);
		const drawContext = {
			layer: layers[0],
			viewport,
			isPicking,
			renderPass: pass,
			cullRect
		};
		const layerFilterCache = {};
		for (let layerIndex = 0; layerIndex < layers.length; layerIndex++) {
			const layer = layers[layerIndex];
			const shouldDrawLayer = this._shouldDrawLayer(layer, drawContext, layerFilter, layerFilterCache);
			const layerParam = { shouldDrawLayer };
			if (shouldDrawLayer && !evaluateShouldDrawOnly) {
				layerParam.shouldDrawLayer = true;
				layerParam.layerRenderIndex = indexResolver(layer, shouldDrawLayer);
				layerParam.shaderModuleProps = this._getShaderModuleProps(layer, effects, pass, shaderModuleProps);
				layerParam.layerParameters = {
					...layer.context.device.type === "webgpu" ? WEBGPU_DEFAULT_DRAW_PARAMETERS : null,
					...layer.context.deck?.props.parameters,
					...views?.[viewport.id]?.props.parameters,
					...this.getLayerParameters(layer, layerIndex, viewport)
				};
			}
			drawLayerParams[layerIndex] = layerParam;
		}
		return drawLayerParams;
	}
	_drawLayersInViewport(renderPass, { layers, shaderModuleProps: globalModuleParameters, pass, target, viewport, view, isPicking }, drawLayerParams) {
		const glViewport = getGLViewport(this.device, {
			shaderModuleProps: globalModuleParameters,
			target,
			viewport
		});
		if (view) {
			const { clear, clearColor, clearDepth, clearStencil } = view.props;
			if (clear) {
				let colorToUse = [
					0,
					0,
					0,
					0
				];
				let depthToUse = 1;
				let stencilToUse = 0;
				if (Array.isArray(clearColor) && !isPicking) colorToUse = [...clearColor.slice(0, 3), clearColor[3] || 255].map((c) => c / 255);
				else if (clearColor === false) colorToUse = false;
				if (clearDepth !== void 0) depthToUse = clearDepth;
				if (clearStencil !== void 0) stencilToUse = clearStencil;
				this.device.beginRenderPass({
					framebuffer: target,
					parameters: {
						viewport: glViewport,
						scissorRect: glViewport
					},
					clearColor: colorToUse,
					clearDepth: depthToUse,
					clearStencil: stencilToUse
				}).end();
			}
		}
		const renderStatus = {
			totalCount: layers.length,
			visibleCount: 0,
			compositeCount: 0,
			pickableCount: 0
		};
		renderPass.setParameters({ viewport: glViewport });
		for (let layerIndex = 0; layerIndex < layers.length; layerIndex++) {
			const layer = layers[layerIndex];
			const drawLayerParameters = drawLayerParams[layerIndex];
			const { shouldDrawLayer } = drawLayerParameters;
			if (shouldDrawLayer && layer.props.pickable) renderStatus.pickableCount++;
			if (layer.isComposite) renderStatus.compositeCount++;
			if (layer.isDrawable && drawLayerParameters.shouldDrawLayer) {
				const { layerRenderIndex, shaderModuleProps, layerParameters } = drawLayerParameters;
				renderStatus.visibleCount++;
				this._lastRenderIndex = Math.max(this._lastRenderIndex, layerRenderIndex);
				if (shaderModuleProps.project) shaderModuleProps.project.viewport = viewport;
				layer.context.renderPass = renderPass;
				try {
					layer._drawLayer({
						renderPass,
						shaderModuleProps,
						uniforms: { layerIndex: layerRenderIndex },
						parameters: layerParameters
					});
				} catch (err) {
					layer.raiseError(err, `drawing ${layer} to ${pass}`);
				}
			}
		}
		return renderStatus;
	}
	shouldDrawLayer(layer) {
		return true;
	}
	getShaderModuleProps(layer, effects, otherShaderModuleProps) {
		return null;
	}
	getLayerParameters(layer, layerIndex, viewport) {
		return layer.props.parameters;
	}
	_shouldDrawLayer(layer, drawContext, layerFilter, layerFilterCache) {
		if (!(layer.props.visible && this.shouldDrawLayer(layer))) return false;
		drawContext.layer = layer;
		let parent = layer.parent;
		while (parent) {
			if (!parent.props.visible || !parent.filterSubLayer(drawContext)) return false;
			drawContext.layer = parent;
			parent = parent.parent;
		}
		if (layerFilter) {
			const rootLayerId = drawContext.layer.id;
			if (!(rootLayerId in layerFilterCache)) layerFilterCache[rootLayerId] = layerFilter(drawContext);
			if (!layerFilterCache[rootLayerId]) return false;
		}
		layer.activateViewport(drawContext.viewport);
		return true;
	}
	_getShaderModuleProps(layer, effects, pass, overrides) {
		const devicePixelRatio = this.device.canvasContext.cssToDeviceRatio();
		const layerProps = layer.internalState?.propsInTransition || layer.props;
		const shaderModuleProps = {
			layer: layerProps,
			picking: { isActive: false },
			project: {
				viewport: layer.context.viewport,
				devicePixelRatio,
				modelMatrix: layerProps.modelMatrix,
				coordinateSystem: layerProps.coordinateSystem,
				coordinateOrigin: layerProps.coordinateOrigin,
				autoWrapLongitude: layer.wrapLongitude
			}
		};
		if (effects) for (const effect of effects) mergeModuleParameters(shaderModuleProps, effect.getShaderModuleProps?.(layer, shaderModuleProps));
		for (const module of layer.context.defaultShaderModules) if (!(module.name in shaderModuleProps)) shaderModuleProps[module.name] = {};
		return mergeModuleParameters(shaderModuleProps, this.getShaderModuleProps(layer, effects, shaderModuleProps), overrides);
	}
};
function layerIndexResolver(startIndex = 0, layerIndices = {}) {
	const resolvers = {};
	const resolveLayerIndex = (layer, isDrawn) => {
		const indexOverride = layer.props._offset;
		const layerId = layer.id;
		const parentId = layer.parent && layer.parent.id;
		let index;
		if (parentId && !(parentId in layerIndices)) resolveLayerIndex(layer.parent, false);
		if (parentId in resolvers) {
			const resolver = resolvers[parentId] = resolvers[parentId] || layerIndexResolver(layerIndices[parentId], layerIndices);
			index = resolver(layer, isDrawn);
			resolvers[layerId] = resolver;
		} else if (Number.isFinite(indexOverride)) {
			index = indexOverride + (layerIndices[parentId] || 0);
			resolvers[layerId] = null;
		} else index = startIndex;
		if (isDrawn && index >= startIndex) startIndex = index + 1;
		layerIndices[layerId] = index;
		return index;
	};
	return resolveLayerIndex;
}
function getGLViewport(device, { shaderModuleProps, target, viewport }) {
	const pixelRatio = shaderModuleProps?.project?.devicePixelRatio ?? device.canvasContext.cssToDeviceRatio();
	const [, drawingBufferHeight] = device.canvasContext.getDrawingBufferSize();
	const height = target ? target.height : drawingBufferHeight;
	const dimensions = viewport;
	return [
		dimensions.x * pixelRatio,
		height - (dimensions.y + dimensions.height) * pixelRatio,
		dimensions.width * pixelRatio,
		dimensions.height * pixelRatio
	];
}
function mergeModuleParameters(target, ...sources) {
	for (const source of sources) if (source) for (const key in source) if (target[key]) Object.assign(target[key], source[key]);
	else target[key] = source[key];
	return target;
}
//#endregion
//#region node_modules/@deck.gl/core/dist/passes/shadow-pass.js
var ShadowPass = class extends LayersPass {
	constructor(device, props) {
		super(device, props);
		const shadowMap = device.createTexture({
			format: "rgba8unorm",
			width: 1,
			height: 1,
			sampler: {
				minFilter: "linear",
				magFilter: "linear",
				addressModeU: "clamp-to-edge",
				addressModeV: "clamp-to-edge"
			}
		});
		const depthBuffer = device.createTexture({
			format: "depth16unorm",
			width: 1,
			height: 1
		});
		this.fbo = device.createFramebuffer({
			id: "shadowmap",
			width: 1,
			height: 1,
			colorAttachments: [shadowMap],
			depthStencilAttachment: depthBuffer
		});
	}
	delete() {
		if (this.fbo) {
			this.fbo.destroy();
			this.fbo = null;
		}
	}
	getShadowMap() {
		return this.fbo.colorAttachments[0].texture;
	}
	render(params) {
		const target = this.fbo;
		const pixelRatio = this.device.canvasContext.cssToDeviceRatio();
		const viewport = params.viewports[0];
		const width = viewport.width * pixelRatio;
		const height = viewport.height * pixelRatio;
		const clearColor = [
			1,
			1,
			1,
			1
		];
		if (width !== target.width || height !== target.height) target.resize({
			width,
			height
		});
		super.render({
			...params,
			clearColor,
			target,
			pass: "shadow"
		});
	}
	getLayerParameters(layer, layerIndex, viewport) {
		return {
			...layer.props.parameters,
			blend: false,
			depthWriteEnabled: true,
			depthCompare: "less-equal"
		};
	}
	shouldDrawLayer(layer) {
		return layer.props.shadowEnabled !== false;
	}
	getShaderModuleProps(layer, effects, otherShaderModuleProps) {
		return { shadow: {
			project: otherShaderModuleProps.project,
			drawToShadowMap: true
		} };
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/effects/lighting/lighting-effect.js
var DEFAULT_AMBIENT_LIGHT_PROPS = {
	color: [
		255,
		255,
		255
	],
	intensity: 1
};
var DEFAULT_DIRECTIONAL_LIGHT_PROPS = [{
	color: [
		255,
		255,
		255
	],
	intensity: 1,
	direction: [
		-1,
		3,
		-1
	]
}, {
	color: [
		255,
		255,
		255
	],
	intensity: .9,
	direction: [
		1,
		-8,
		-2.5
	]
}];
var DEFAULT_SHADOW_COLOR = [
	0,
	0,
	0,
	200 / 255
];
var LightingEffect = class {
	constructor(props = {}) {
		this.id = "lighting-effect";
		this.shadowColor = DEFAULT_SHADOW_COLOR;
		this.shadow = false;
		this.directionalLights = [];
		this.pointLights = [];
		this.shadowPasses = [];
		this.dummyShadowMap = null;
		this.setProps(props);
	}
	setup(context) {
		this.context = context;
		const { device, deck } = context;
		if (this.shadow && !this.dummyShadowMap) {
			this._createShadowPasses(device);
			deck._addDefaultShaderModule(shadow_default);
			this.dummyShadowMap = device.createTexture({
				width: 1,
				height: 1
			});
		}
	}
	setProps(props) {
		this.ambientLight = void 0;
		this.directionalLights = [];
		this.pointLights = [];
		for (const key in props) {
			const lightSource = props[key];
			switch (lightSource.type) {
				case "ambient":
					this.ambientLight = lightSource;
					break;
				case "directional":
					this.directionalLights.push(lightSource);
					break;
				case "point":
					this.pointLights.push(lightSource);
					break;
				default:
			}
		}
		this._applyDefaultLights();
		this.shadow = this.directionalLights.some((light) => light.shadow);
		if (this.context) this.setup(this.context);
		this.props = props;
	}
	preRender({ layers, layerFilter, viewports, onViewportActive, views }) {
		if (!this.shadow) return;
		this.shadowMatrices = this._calculateMatrices();
		for (let i = 0; i < this.shadowPasses.length; i++) this.shadowPasses[i].render({
			layers,
			layerFilter,
			viewports,
			onViewportActive,
			views,
			shaderModuleProps: { shadow: {
				shadowLightId: i,
				dummyShadowMap: this.dummyShadowMap,
				shadowMatrices: this.shadowMatrices
			} }
		});
	}
	getShaderModuleProps(layer, otherShaderModuleProps) {
		const shadowProps = this.shadow ? {
			project: otherShaderModuleProps.project,
			shadowMaps: this.shadowPasses.map((shadowPass) => shadowPass.getShadowMap()),
			dummyShadowMap: this.dummyShadowMap,
			shadowColor: this.shadowColor,
			shadowMatrices: this.shadowMatrices
		} : {};
		const lightingProps = {
			enabled: true,
			lights: this._getLights(layer)
		};
		const materialProps = layer.props.material;
		return {
			shadow: shadowProps,
			lighting: lightingProps,
			phongMaterial: materialProps,
			gouraudMaterial: materialProps
		};
	}
	cleanup(context) {
		for (const shadowPass of this.shadowPasses) shadowPass.delete();
		this.shadowPasses.length = 0;
		if (this.dummyShadowMap) {
			this.dummyShadowMap.destroy();
			this.dummyShadowMap = null;
			context.deck._removeDefaultShaderModule(shadow_default);
		}
	}
	_calculateMatrices() {
		const lightMatrices = [];
		for (const light of this.directionalLights) {
			const viewMatrix = new Matrix4().lookAt({ eye: new Vector3(light.direction).negate() });
			lightMatrices.push(viewMatrix);
		}
		return lightMatrices;
	}
	_createShadowPasses(device) {
		for (let i = 0; i < this.directionalLights.length; i++) {
			const shadowPass = new ShadowPass(device);
			this.shadowPasses[i] = shadowPass;
		}
	}
	_applyDefaultLights() {
		const { ambientLight, pointLights, directionalLights } = this;
		if (!ambientLight && pointLights.length === 0 && directionalLights.length === 0) {
			this.ambientLight = new AmbientLight(DEFAULT_AMBIENT_LIGHT_PROPS);
			this.directionalLights.push(new DirectionalLight(DEFAULT_DIRECTIONAL_LIGHT_PROPS[0]), new DirectionalLight(DEFAULT_DIRECTIONAL_LIGHT_PROPS[1]));
		}
	}
	_getLights(layer) {
		const lights = [];
		if (this.ambientLight) lights.push(this.ambientLight);
		for (const pointLight of this.pointLights) lights.push(pointLight.getProjectedLight({ layer }));
		for (const directionalLight of this.directionalLights) lights.push(directionalLight.getProjectedLight({ layer }));
		return lights;
	}
};
//#endregion
//#region node_modules/@luma.gl/engine/dist/animation/timeline.js
var channelHandles = 1;
var animationHandles = 1;
var Timeline = class {
	time = 0;
	channels = /* @__PURE__ */ new Map();
	animations = /* @__PURE__ */ new Map();
	playing = false;
	lastEngineTime = -1;
	constructor() {}
	addChannel(props) {
		const { delay = 0, duration = Number.POSITIVE_INFINITY, rate = 1, repeat = 1 } = props;
		const channelId = channelHandles++;
		const channel = {
			time: 0,
			delay,
			duration,
			rate,
			repeat
		};
		this._setChannelTime(channel, this.time);
		this.channels.set(channelId, channel);
		return channelId;
	}
	removeChannel(channelId) {
		this.channels.delete(channelId);
		for (const [animationHandle, animation] of this.animations) if (animation.channel === channelId) this.detachAnimation(animationHandle);
	}
	isFinished(channelId) {
		const channel = this.channels.get(channelId);
		if (channel === void 0) return false;
		return this.time >= channel.delay + channel.duration * channel.repeat;
	}
	getTime(channelId) {
		if (channelId === void 0) return this.time;
		const channel = this.channels.get(channelId);
		if (channel === void 0) return -1;
		return channel.time;
	}
	setTime(time) {
		this.time = Math.max(0, time);
		const channels = this.channels.values();
		for (const channel of channels) this._setChannelTime(channel, this.time);
		const animations = this.animations.values();
		for (const animationData of animations) {
			const { animation, channel } = animationData;
			animation.setTime(this.getTime(channel));
		}
	}
	play() {
		this.playing = true;
	}
	pause() {
		this.playing = false;
		this.lastEngineTime = -1;
	}
	reset() {
		this.setTime(0);
	}
	attachAnimation(animation, channelHandle) {
		const animationHandle = animationHandles++;
		this.animations.set(animationHandle, {
			animation,
			channel: channelHandle
		});
		animation.setTime(this.getTime(channelHandle));
		return animationHandle;
	}
	detachAnimation(channelId) {
		this.animations.delete(channelId);
	}
	update(engineTime) {
		if (this.playing) {
			if (this.lastEngineTime === -1) this.lastEngineTime = engineTime;
			this.setTime(this.time + (engineTime - this.lastEngineTime));
			this.lastEngineTime = engineTime;
		}
	}
	_setChannelTime(channel, time) {
		const offsetTime = time - channel.delay;
		if (offsetTime >= channel.duration * channel.repeat) channel.time = channel.duration * channel.rate;
		else {
			channel.time = Math.max(0, offsetTime) % channel.duration;
			channel.time *= channel.rate;
		}
	}
};
//#endregion
//#region node_modules/@luma.gl/engine/dist/animation-loop/request-animation-frame.js
/** Node.js polyfill for requestAnimationFrame */
function requestAnimationFramePolyfill(callback) {
	const browserRequestAnimationFrame = typeof window !== "undefined" ? window.requestAnimationFrame || window.webkitRequestAnimationFrame || window.mozRequestAnimationFrame : null;
	if (browserRequestAnimationFrame) return browserRequestAnimationFrame.call(window, callback);
	return setTimeout(() => callback(typeof performance !== "undefined" ? performance.now() : Date.now()), 1e3 / 60);
}
/** Node.js polyfill for cancelAnimationFrame */
function cancelAnimationFramePolyfill(timerId) {
	const browserCancelAnimationFrame = typeof window !== "undefined" ? window.cancelAnimationFrame || window.webkitCancelAnimationFrame || window.mozCancelAnimationFrame : null;
	if (browserCancelAnimationFrame) {
		browserCancelAnimationFrame.call(window, timerId);
		return;
	}
	clearTimeout(timerId);
}
//#endregion
//#region node_modules/@luma.gl/engine/dist/animation-loop/animation-loop.js
var statIdCounter = 0;
var ANIMATION_LOOP_STATS = "Animation Loop";
/** Convenient animation loop */
var AnimationLoop = class AnimationLoop {
	static defaultAnimationLoopProps = {
		device: null,
		onAddHTML: () => "",
		onInitialize: async () => null,
		onRender: () => {},
		onFinalize: () => {},
		onError: (error) => console.error(error),
		stats: void 0,
		autoResizeViewport: false
	};
	device = null;
	canvas = null;
	props;
	animationProps = null;
	timeline = null;
	stats;
	sharedStats;
	cpuTime;
	gpuTime;
	frameRate;
	display;
	_needsRedraw = "initialized";
	_initialized = false;
	_running = false;
	_animationFrameId = null;
	_nextFramePromise = null;
	_resolveNextFrame = null;
	_cpuStartTime = 0;
	_error = null;
	_lastFrameTime = 0;
	constructor(props) {
		this.props = {
			...AnimationLoop.defaultAnimationLoopProps,
			...props
		};
		props = this.props;
		if (!props.device) throw new Error("No device provided");
		this.stats = props.stats || new Stats({ id: `animation-loop-${statIdCounter++}` });
		this.sharedStats = luma.stats.get(ANIMATION_LOOP_STATS);
		this.frameRate = this.stats.get("Frame Rate");
		this.frameRate.setSampleSize(1);
		this.cpuTime = this.stats.get("CPU Time");
		this.gpuTime = this.stats.get("GPU Time");
		this.setProps({ autoResizeViewport: props.autoResizeViewport });
		this.start = this.start.bind(this);
		this.stop = this.stop.bind(this);
		this._onMousemove = this._onMousemove.bind(this);
		this._onMouseleave = this._onMouseleave.bind(this);
	}
	destroy() {
		this.stop();
		this._setDisplay(null);
		this.device?._disableDebugGPUTime();
	}
	/** @deprecated Use .destroy() */
	delete() {
		this.destroy();
	}
	reportError(error) {
		this.props.onError(error);
		this._error = error;
	}
	/** Flags this animation loop as needing redraw */
	setNeedsRedraw(reason) {
		this._needsRedraw = this._needsRedraw || reason;
		return this;
	}
	/** Query redraw status. Clears the flag. */
	needsRedraw() {
		const reason = this._needsRedraw;
		this._needsRedraw = false;
		return reason;
	}
	setProps(props) {
		if ("autoResizeViewport" in props) this.props.autoResizeViewport = props.autoResizeViewport || false;
		return this;
	}
	/** Starts a render loop if not already running */
	async start() {
		if (this._running) return this;
		this._running = true;
		try {
			if (!this._initialized) {
				this._initialized = true;
				await this._initDevice();
				this._initialize();
				if (!this._running) return null;
				await this.props.onInitialize(this._getAnimationProps());
			}
			if (!this._running) return null;
			this._cancelAnimationFrame();
			this._requestAnimationFrame();
			return this;
		} catch (err) {
			const error = err instanceof Error ? err : /* @__PURE__ */ new Error("Unknown error");
			this.props.onError(error);
			throw error;
		}
	}
	/** Stops a render loop if already running, finalizing */
	stop() {
		if (this._running) {
			if (this.animationProps && !this._error) this.props.onFinalize(this.animationProps);
			this._cancelAnimationFrame();
			this._nextFramePromise = null;
			this._resolveNextFrame = null;
			this._running = false;
			this._lastFrameTime = 0;
		}
		return this;
	}
	/** Explicitly draw a frame */
	redraw(time) {
		if (this.device?.isLost || this._error) return this;
		this._beginFrameTimers(time);
		this._setupFrame();
		this._updateAnimationProps();
		this._renderFrame(this._getAnimationProps());
		this._clearNeedsRedraw();
		if (this._resolveNextFrame) {
			this._resolveNextFrame(this);
			this._nextFramePromise = null;
			this._resolveNextFrame = null;
		}
		this._endFrameTimers();
		return this;
	}
	/** Add a timeline, it will be automatically updated by the animation loop. */
	attachTimeline(timeline) {
		this.timeline = timeline;
		return this.timeline;
	}
	/** Remove a timeline */
	detachTimeline() {
		this.timeline = null;
	}
	/** Wait until a render completes */
	waitForRender() {
		this.setNeedsRedraw("waitForRender");
		if (!this._nextFramePromise) this._nextFramePromise = new Promise((resolve) => {
			this._resolveNextFrame = resolve;
		});
		return this._nextFramePromise;
	}
	/** TODO - should use device.deviceContext */
	async toDataURL() {
		this.setNeedsRedraw("toDataURL");
		await this.waitForRender();
		if (this.canvas instanceof HTMLCanvasElement) return this.canvas.toDataURL();
		throw new Error("OffscreenCanvas");
	}
	_initialize() {
		this._startEventHandling();
		this._initializeAnimationProps();
		this._updateAnimationProps();
		this._resizeViewport();
		this.device?._enableDebugGPUTime();
	}
	_setDisplay(display) {
		if (this.display) {
			this.display.destroy();
			this.display.animationLoop = null;
		}
		if (display) display.animationLoop = this;
		this.display = display;
	}
	_requestAnimationFrame() {
		if (!this._running) return;
		this._animationFrameId = requestAnimationFramePolyfill(this._animationFrame.bind(this));
	}
	_cancelAnimationFrame() {
		if (this._animationFrameId === null) return;
		cancelAnimationFramePolyfill(this._animationFrameId);
		this._animationFrameId = null;
	}
	_animationFrame(time) {
		if (!this._running) return;
		this.redraw(time);
		this._requestAnimationFrame();
	}
	_renderFrame(animationProps) {
		if (this.display) {
			this.display._renderFrame(animationProps);
			return;
		}
		this.props.onRender(this._getAnimationProps());
		this.device?.submit();
	}
	_clearNeedsRedraw() {
		this._needsRedraw = false;
	}
	_setupFrame() {
		this._resizeViewport();
	}
	_initializeAnimationProps() {
		const canvasContext = this.device?.getDefaultCanvasContext();
		if (!this.device || !canvasContext) throw new Error("loop");
		const canvas = canvasContext?.canvas;
		const useDevicePixels = canvasContext.props.useDevicePixels;
		this.animationProps = {
			animationLoop: this,
			device: this.device,
			canvasContext,
			canvas,
			useDevicePixels,
			timeline: this.timeline,
			needsRedraw: false,
			width: 1,
			height: 1,
			aspect: 1,
			time: 0,
			startTime: Date.now(),
			engineTime: 0,
			tick: 0,
			tock: 0,
			_mousePosition: null
		};
	}
	_getAnimationProps() {
		if (!this.animationProps) throw new Error("animationProps");
		return this.animationProps;
	}
	_updateAnimationProps() {
		if (!this.animationProps) return;
		const { width, height, aspect } = this._getSizeAndAspect();
		if (width !== this.animationProps.width || height !== this.animationProps.height) this.setNeedsRedraw("drawing buffer resized");
		if (aspect !== this.animationProps.aspect) this.setNeedsRedraw("drawing buffer aspect changed");
		this.animationProps.width = width;
		this.animationProps.height = height;
		this.animationProps.aspect = aspect;
		this.animationProps.needsRedraw = this._needsRedraw;
		this.animationProps.engineTime = Date.now() - this.animationProps.startTime;
		if (this.timeline) this.timeline.update(this.animationProps.engineTime);
		this.animationProps.tick = Math.floor(this.animationProps.time / 1e3 * 60);
		this.animationProps.tock++;
		this.animationProps.time = this.timeline ? this.timeline.getTime() : this.animationProps.engineTime;
	}
	/** Wait for supplied device */
	async _initDevice() {
		this.device = await this.props.device;
		if (!this.device) throw new Error("No device provided");
		this.canvas = this.device.getDefaultCanvasContext().canvas || null;
	}
	_createInfoDiv() {
		if (this.canvas && this.props.onAddHTML) {
			const wrapperDiv = document.createElement("div");
			document.body.appendChild(wrapperDiv);
			wrapperDiv.style.position = "relative";
			const div = document.createElement("div");
			div.style.position = "absolute";
			div.style.left = "10px";
			div.style.bottom = "10px";
			div.style.width = "300px";
			div.style.background = "white";
			if (this.canvas instanceof HTMLCanvasElement) wrapperDiv.appendChild(this.canvas);
			wrapperDiv.appendChild(div);
			const html = this.props.onAddHTML(div);
			if (html) div.innerHTML = html;
		}
	}
	_getSizeAndAspect() {
		if (!this.device) return {
			width: 1,
			height: 1,
			aspect: 1
		};
		const [width, height] = this.device.getDefaultCanvasContext().getDrawingBufferSize();
		return {
			width,
			height,
			aspect: width > 0 && height > 0 ? width / height : 1
		};
	}
	/** @deprecated Default viewport setup */
	_resizeViewport() {
		if (this.props.autoResizeViewport && this.device.gl) this.device.gl.viewport(0, 0, this.device.gl.drawingBufferWidth, this.device.gl.drawingBufferHeight);
	}
	_beginFrameTimers(time) {
		const now = time ?? (typeof performance !== "undefined" ? performance.now() : Date.now());
		if (this._lastFrameTime) {
			const frameTime = now - this._lastFrameTime;
			if (frameTime > 0) this.frameRate.addTime(frameTime);
		}
		this._lastFrameTime = now;
		if (this.device?._isDebugGPUTimeEnabled()) this._consumeEncodedGpuTime();
		this.cpuTime.timeStart();
	}
	_endFrameTimers() {
		if (this.device?._isDebugGPUTimeEnabled()) this._consumeEncodedGpuTime();
		this.cpuTime.timeEnd();
		this._updateSharedStats();
	}
	_consumeEncodedGpuTime() {
		if (!this.device) return;
		const gpuTimeMs = this.device.commandEncoder._gpuTimeMs;
		if (gpuTimeMs !== void 0) {
			this.gpuTime.addTime(gpuTimeMs);
			this.device.commandEncoder._gpuTimeMs = void 0;
		}
	}
	_updateSharedStats() {
		if (this.stats === this.sharedStats) return;
		for (const name of Object.keys(this.sharedStats.stats)) if (!this.stats.stats[name]) delete this.sharedStats.stats[name];
		this.stats.forEach((sourceStat) => {
			const targetStat = this.sharedStats.get(sourceStat.name, sourceStat.type);
			targetStat.sampleSize = sourceStat.sampleSize;
			targetStat.time = sourceStat.time;
			targetStat.count = sourceStat.count;
			targetStat.samples = sourceStat.samples;
			targetStat.lastTiming = sourceStat.lastTiming;
			targetStat.lastSampleTime = sourceStat.lastSampleTime;
			targetStat.lastSampleCount = sourceStat.lastSampleCount;
			targetStat._count = sourceStat._count;
			targetStat._time = sourceStat._time;
			targetStat._samples = sourceStat._samples;
			targetStat._startTime = sourceStat._startTime;
			targetStat._timerPending = sourceStat._timerPending;
		});
	}
	_startEventHandling() {
		if (this.canvas) {
			this.canvas.addEventListener("mousemove", this._onMousemove.bind(this));
			this.canvas.addEventListener("mouseleave", this._onMouseleave.bind(this));
		}
	}
	_onMousemove(event) {
		if (event instanceof MouseEvent) this._getAnimationProps()._mousePosition = [event.offsetX, event.offsetY];
	}
	_onMouseleave(event) {
		this._getAnimationProps()._mousePosition = null;
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/passes/pick-layers-pass.js
var PICKING_BLENDING = {
	blendColorOperation: "add",
	blendColorSrcFactor: "one",
	blendColorDstFactor: "zero",
	blendAlphaOperation: "add",
	blendAlphaSrcFactor: "constant",
	blendAlphaDstFactor: "zero"
};
var PickLayersPass = class extends LayersPass {
	constructor() {
		super(...arguments);
		this._colorEncoderState = null;
	}
	render(props) {
		if ("pickingFBO" in props) return this._drawPickingBuffer(props);
		return {
			decodePickingColor: null,
			stats: super._render(props)
		};
	}
	_drawPickingBuffer({ layers, layerFilter, views, viewports, onViewportActive, pickingFBO, deviceRect: { x, y, width, height }, cullRect, effects, pass = "picking", pickZ, shaderModuleProps, clearColor }) {
		this.pickZ = pickZ;
		const colorEncoderState = this._resetColorEncoder(pickZ);
		const scissorRect = [
			x,
			y,
			width,
			height
		];
		const renderStatus = super._render({
			target: pickingFBO,
			layers,
			layerFilter,
			views,
			viewports,
			onViewportActive,
			cullRect,
			effects: effects?.filter((e) => e.useInPicking),
			pass,
			isPicking: true,
			shaderModuleProps,
			clearColor: clearColor ?? [
				0,
				0,
				0,
				0
			],
			colorMask: 15,
			scissorRect
		});
		this._colorEncoderState = null;
		return {
			decodePickingColor: colorEncoderState && decodeColor.bind(null, colorEncoderState),
			stats: renderStatus
		};
	}
	shouldDrawLayer(layer) {
		const { pickable, operation } = layer.props;
		return pickable && operation.includes("draw") || operation.includes("terrain") || operation.includes("mask");
	}
	getShaderModuleProps(layer, effects, otherShaderModuleProps) {
		return {
			picking: {
				isActive: 1,
				isAttribute: this.pickZ
			},
			lighting: { enabled: false }
		};
	}
	getLayerParameters(layer, layerIndex, viewport) {
		const pickParameters = { ...layer.props.parameters };
		const { pickable, operation } = layer.props;
		if (!this._colorEncoderState) pickParameters.blend = false;
		else if (pickable && operation.includes("draw")) {
			Object.assign(pickParameters, PICKING_BLENDING);
			pickParameters.blend = true;
			if (this.device.type === "webgpu") pickParameters.blendConstant = encodeColor(this._colorEncoderState, layer, viewport);
			else pickParameters.blendColor = encodeColor(this._colorEncoderState, layer, viewport);
			if (operation.includes("terrain") && layer.state?._hasPickingCover) pickParameters.blendAlphaSrcFactor = "one";
		} else if (operation.includes("terrain")) pickParameters.blend = false;
		return pickParameters;
	}
	_resetColorEncoder(pickZ) {
		this._colorEncoderState = pickZ ? null : {
			byLayer: /* @__PURE__ */ new Map(),
			byAlpha: []
		};
		return this._colorEncoderState;
	}
};
function encodeColor(encoded, layer, viewport) {
	const { byLayer, byAlpha } = encoded;
	let a;
	let entry = byLayer.get(layer);
	if (entry) {
		entry.viewports.push(viewport);
		a = entry.a;
	} else {
		a = byLayer.size + 1;
		if (a <= 255) {
			entry = {
				a,
				layer,
				viewports: [viewport]
			};
			byLayer.set(layer, entry);
			byAlpha[a] = entry;
		} else {
			defaultLogger.warn("Too many pickable layers, only picking the first 255")();
			a = 0;
		}
	}
	return [
		0,
		0,
		0,
		a / 255
	];
}
function decodeColor(encoded, pickedColor) {
	const entry = encoded.byAlpha[pickedColor[3]];
	return entry && {
		pickedLayer: entry.layer,
		pickedViewports: entry.viewports,
		pickedObjectIndex: entry.layer.decodePickingColor(pickedColor)
	};
}
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/resource/resource.js
var Resource = class {
	constructor(id, data, context) {
		this._loadCount = 0;
		this._subscribers = /* @__PURE__ */ new Set();
		this.id = id;
		this.context = context;
		this.setData(data);
	}
	subscribe(consumer) {
		this._subscribers.add(consumer);
	}
	unsubscribe(consumer) {
		this._subscribers.delete(consumer);
	}
	inUse() {
		return this._subscribers.size > 0;
	}
	delete() {}
	getData() {
		return this.isLoaded ? this._error ? Promise.reject(this._error) : this._content : this._loader.then(() => this.getData());
	}
	setData(data, forceUpdate) {
		if (data === this._data && !forceUpdate) return;
		this._data = data;
		const loadCount = ++this._loadCount;
		let loader = data;
		if (typeof data === "string") loader = load(data);
		if (loader instanceof Promise) {
			this.isLoaded = false;
			this._loader = loader.then((result) => {
				if (this._loadCount === loadCount) {
					this.isLoaded = true;
					this._error = void 0;
					this._content = result;
				}
			}).catch((error) => {
				if (this._loadCount === loadCount) {
					this.isLoaded = true;
					this._error = error || true;
				}
			});
		} else {
			this.isLoaded = true;
			this._error = void 0;
			this._content = data;
		}
		for (const subscriber of this._subscribers) subscriber.onChange(this.getData());
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/resource/resource-manager.js
var ResourceManager = class {
	constructor(props) {
		this.protocol = props.protocol || "resource://";
		this._context = {
			device: props.device,
			gl: props.device?.gl,
			resourceManager: this
		};
		this._resources = {};
		this._consumers = {};
		this._pruneRequest = null;
	}
	contains(resourceId) {
		if (resourceId.startsWith(this.protocol)) return true;
		return resourceId in this._resources;
	}
	add({ resourceId, data, forceUpdate = false, persistent = true }) {
		let res = this._resources[resourceId];
		if (res) res.setData(data, forceUpdate);
		else {
			res = new Resource(resourceId, data, this._context);
			this._resources[resourceId] = res;
		}
		res.persistent = persistent;
	}
	remove(resourceId) {
		const res = this._resources[resourceId];
		if (res) {
			res.delete();
			delete this._resources[resourceId];
		}
	}
	unsubscribe({ consumerId }) {
		const consumer = this._consumers[consumerId];
		if (consumer) {
			for (const requestId in consumer) {
				const request = consumer[requestId];
				const resource = this._resources[request.resourceId];
				if (resource) resource.unsubscribe(request);
			}
			delete this._consumers[consumerId];
			this.prune();
		}
	}
	subscribe({ resourceId, onChange, consumerId, requestId = "default" }) {
		const { _resources: resources, protocol } = this;
		if (resourceId.startsWith(protocol)) {
			resourceId = resourceId.replace(protocol, "");
			if (!resources[resourceId]) this.add({
				resourceId,
				data: null,
				persistent: false
			});
		}
		const res = resources[resourceId];
		this._track(consumerId, requestId, res, onChange);
		if (res) return res.getData();
	}
	prune() {
		if (!this._pruneRequest) this._pruneRequest = setTimeout(() => this._prune(), 0);
	}
	finalize() {
		for (const key in this._resources) this._resources[key].delete();
	}
	_track(consumerId, requestId, resource, onChange) {
		const consumers = this._consumers;
		const consumer = consumers[consumerId] = consumers[consumerId] || {};
		let request = consumer[requestId];
		const oldResource = request && request.resourceId && this._resources[request.resourceId];
		if (oldResource) {
			oldResource.unsubscribe(request);
			this.prune();
		}
		if (resource) {
			if (request) {
				request.onChange = onChange;
				request.resourceId = resource.id;
			} else request = {
				onChange,
				resourceId: resource.id
			};
			consumer[requestId] = request;
			resource.subscribe(request);
		}
	}
	_prune() {
		this._pruneRequest = null;
		for (const key of Object.keys(this._resources)) {
			const res = this._resources[key];
			if (!res.persistent && !res.inUse()) {
				res.delete();
				delete this._resources[key];
			}
		}
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/layer-manager.js
var TRACE_SET_LAYERS = "layerManager.setLayers";
var TRACE_ACTIVATE_VIEWPORT = "layerManager.activateViewport";
var LayerManager = class {
	/**
	* @param device
	* @param param1
	*/
	constructor(device, props) {
		this._lastRenderedLayers = [];
		this._needsRedraw = false;
		this._needsUpdate = false;
		this._nextLayers = null;
		this._debug = false;
		this._defaultShaderModulesChanged = false;
		/** Make a viewport "current" in layer context, updating viewportChanged flags */
		this.activateViewport = (viewport) => {
			debug(TRACE_ACTIVATE_VIEWPORT, this, viewport);
			if (viewport) this.context.viewport = viewport;
		};
		const { deck, stats, viewport, timeline } = props || {};
		this.layers = [];
		this.resourceManager = new ResourceManager({
			device,
			protocol: "deck://"
		});
		this.context = {
			mousePosition: null,
			userData: {},
			layerManager: this,
			device,
			gl: device?.gl,
			deck,
			shaderAssembler: getShaderAssembler(device?.info?.shadingLanguage || "glsl"),
			defaultShaderModules: [layerUniforms],
			renderPass: void 0,
			stats: stats || new Stats({ id: "deck.gl" }),
			viewport: viewport || new Viewport({ id: "DEFAULT-INITIAL-VIEWPORT" }),
			timeline: timeline || new Timeline(),
			resourceManager: this.resourceManager,
			onError: void 0
		};
		Object.seal(this);
	}
	/** Method to call when the layer manager is not needed anymore. */
	finalize() {
		this.resourceManager.finalize();
		for (const layer of this.layers) this._finalizeLayer(layer);
	}
	/** Check if a redraw is needed */
	needsRedraw(opts = { clearRedrawFlags: false }) {
		let redraw = this._needsRedraw;
		if (opts.clearRedrawFlags) this._needsRedraw = false;
		for (const layer of this.layers) {
			const layerNeedsRedraw = layer.getNeedsRedraw(opts);
			redraw = redraw || layerNeedsRedraw;
		}
		return redraw;
	}
	/** Check if a deep update of all layers is needed */
	needsUpdate() {
		if (this._nextLayers && this._nextLayers !== this._lastRenderedLayers) return "layers changed";
		if (this._defaultShaderModulesChanged) return "shader modules changed";
		return this._needsUpdate;
	}
	/** Layers will be redrawn (in next animation frame) */
	setNeedsRedraw(reason) {
		this._needsRedraw = this._needsRedraw || reason;
	}
	/** Layers will be updated deeply (in next animation frame)
	Potentially regenerating attributes and sub layers */
	setNeedsUpdate(reason) {
		this._needsUpdate = this._needsUpdate || reason;
	}
	/** Gets a list of currently rendered layers. Optionally filter by id. */
	getLayers({ layerIds } = {}) {
		return layerIds ? this.layers.filter((layer) => layerIds.find((layerId) => layer.id.indexOf(layerId) === 0)) : this.layers;
	}
	/** Set props needed for layer rendering and picking. */
	setProps(props) {
		if ("debug" in props) this._debug = props.debug;
		if ("userData" in props) this.context.userData = props.userData;
		if ("layers" in props) this._nextLayers = props.layers;
		if ("onError" in props) this.context.onError = props.onError;
	}
	/** Supply a new layer list, initiating sublayer generation and layer matching */
	setLayers(newLayers, reason) {
		debug(TRACE_SET_LAYERS, this, reason, newLayers);
		this._lastRenderedLayers = newLayers;
		const flatLayers = flatten(newLayers, Boolean);
		for (const layer of flatLayers) layer.context = this.context;
		this._updateLayers(this.layers, flatLayers);
	}
	/** Update layers from last cycle if `setNeedsUpdate()` has been called */
	updateLayers() {
		const reason = this.needsUpdate();
		if (reason) {
			this.setNeedsRedraw(`updating layers: ${reason}`);
			this.setLayers(this._nextLayers || this._lastRenderedLayers, reason);
		}
		this._nextLayers = null;
	}
	/** Register a default shader module */
	addDefaultShaderModule(module) {
		const { defaultShaderModules } = this.context;
		if (!defaultShaderModules.find((m) => m.name === module.name)) {
			defaultShaderModules.push(module);
			this._defaultShaderModulesChanged = true;
		}
	}
	/** Deregister a default shader module */
	removeDefaultShaderModule(module) {
		const { defaultShaderModules } = this.context;
		const i = defaultShaderModules.findIndex((m) => m.name === module.name);
		if (i >= 0) {
			defaultShaderModules.splice(i, 1);
			this._defaultShaderModulesChanged = true;
		}
	}
	_handleError(stage, error, layer) {
		layer.raiseError(error, `${stage} of ${layer}`);
	}
	/** Match all layers, checking for caught errors
	to avoid having an exception in one layer disrupt other layers */
	_updateLayers(oldLayers, newLayers) {
		const oldLayerMap = {};
		for (const oldLayer of oldLayers) if (oldLayerMap[oldLayer.id]) defaultLogger.warn(`Multiple old layers with same id ${oldLayer.id}`)();
		else oldLayerMap[oldLayer.id] = oldLayer;
		if (this._defaultShaderModulesChanged) {
			for (const layer of oldLayers) {
				layer.setNeedsUpdate();
				layer.setChangeFlags({ extensionsChanged: true });
			}
			this._defaultShaderModulesChanged = false;
		}
		const generatedLayers = [];
		this._updateSublayersRecursively(newLayers, oldLayerMap, generatedLayers);
		this._finalizeOldLayers(oldLayerMap);
		let needsUpdate = false;
		for (const layer of generatedLayers) if (layer.hasUniformTransition()) {
			needsUpdate = `Uniform transition in ${layer}`;
			break;
		}
		this._needsUpdate = needsUpdate;
		this.layers = generatedLayers;
	}
	_updateSublayersRecursively(newLayers, oldLayerMap, generatedLayers) {
		for (const newLayer of newLayers) {
			newLayer.context = this.context;
			const oldLayer = oldLayerMap[newLayer.id];
			if (oldLayer === null) defaultLogger.warn(`Multiple new layers with same id ${newLayer.id}`)();
			oldLayerMap[newLayer.id] = null;
			let sublayers = null;
			try {
				if (this._debug && oldLayer !== newLayer) newLayer.validateProps();
				if (!oldLayer) this._initializeLayer(newLayer);
				else {
					this._transferLayerState(oldLayer, newLayer);
					this._updateLayer(newLayer);
				}
				generatedLayers.push(newLayer);
				sublayers = newLayer.isComposite ? newLayer.getSubLayers() : null;
			} catch (err) {
				this._handleError("matching", err, newLayer);
			}
			if (sublayers) this._updateSublayersRecursively(sublayers, oldLayerMap, generatedLayers);
		}
	}
	_finalizeOldLayers(oldLayerMap) {
		for (const layerId in oldLayerMap) {
			const layer = oldLayerMap[layerId];
			if (layer) this._finalizeLayer(layer);
		}
	}
	/** Safely initializes a single layer, calling layer methods */
	_initializeLayer(layer) {
		try {
			layer._initialize();
			layer.lifecycle = LIFECYCLE.INITIALIZED;
		} catch (err) {
			this._handleError("initialization", err, layer);
		}
	}
	/** Transfer state from one layer to a newer version */
	_transferLayerState(oldLayer, newLayer) {
		newLayer._transferState(oldLayer);
		newLayer.lifecycle = LIFECYCLE.MATCHED;
		if (newLayer !== oldLayer) oldLayer.lifecycle = LIFECYCLE.AWAITING_GC;
	}
	/** Safely updates a single layer, cleaning all flags */
	_updateLayer(layer) {
		try {
			layer._update();
		} catch (err) {
			this._handleError("update", err, layer);
		}
	}
	/** Safely finalizes a single layer, removing all resources */
	_finalizeLayer(layer) {
		this._needsRedraw = this._needsRedraw || `finalized ${layer}`;
		layer.lifecycle = LIFECYCLE.AWAITING_FINALIZATION;
		try {
			layer._finalize();
			layer.lifecycle = LIFECYCLE.FINALIZED;
		} catch (err) {
			this._handleError("finalization", err, layer);
		}
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/view-manager.js
var ViewManager = class {
	constructor(props) {
		this.views = [];
		this.width = 100;
		this.height = 100;
		this.viewState = {};
		this.controllers = {};
		this.timeline = props.timeline;
		this._viewports = [];
		this._viewportMap = {};
		this._isUpdating = false;
		this._needsRedraw = "First render";
		this._needsUpdate = "Initialize";
		this._eventManager = props.eventManager;
		this._eventCallbacks = {
			onViewStateChange: props.onViewStateChange,
			onInteractionStateChange: props.onInteractionStateChange
		};
		this._pickPosition = props.pickPosition;
		Object.seal(this);
		this.setProps(props);
	}
	/** Remove all resources and event listeners */
	finalize() {
		for (const key in this.controllers) {
			const controller = this.controllers[key];
			if (controller) controller.finalize();
		}
		this.controllers = {};
	}
	/** Check if a redraw is needed */
	needsRedraw(opts = { clearRedrawFlags: false }) {
		const redraw = this._needsRedraw;
		if (opts.clearRedrawFlags) this._needsRedraw = false;
		return redraw;
	}
	/** Mark the manager as dirty. Will rebuild all viewports and update controllers. */
	setNeedsUpdate(reason) {
		this._needsUpdate = this._needsUpdate || reason;
		this._needsRedraw = this._needsRedraw || reason;
	}
	/** Checks each viewport for transition updates */
	updateViewStates() {
		for (const viewId in this.controllers) {
			const controller = this.controllers[viewId];
			if (controller) controller.updateTransition();
		}
	}
	/** Get a set of viewports for a given width and height
	* TODO - Intention is for deck.gl to autodeduce width and height and drop the need for props
	* @param rect (object, optional) - filter the viewports
	*   + not provided - return all viewports
	*   + {x, y} - only return viewports that contain this pixel
	*   + {x, y, width, height} - only return viewports that overlap with this rectangle
	*/
	getViewports(rect) {
		if (rect) return this._viewports.filter((viewport) => viewport.containsPixel(rect));
		return this._viewports;
	}
	/** Get a map of all views */
	getViews() {
		const viewMap = {};
		this.views.forEach((view) => {
			viewMap[view.id] = view;
		});
		return viewMap;
	}
	/** Resolves a viewId string to a View */
	getView(viewId) {
		return this.views.find((view) => view.id === viewId);
	}
	/** Returns the viewState for a specific viewId. Matches the viewState by
	1. view.viewStateId
	2. view.id
	3. root viewState
	then applies the view's filter if any */
	getViewState(viewOrViewId) {
		const view = typeof viewOrViewId === "string" ? this.getView(viewOrViewId) : viewOrViewId;
		const viewState = view && this.viewState[view.getViewStateId()] || this.viewState;
		return view ? view.filterViewState(viewState) : viewState;
	}
	getViewport(viewId) {
		return this._viewportMap[viewId];
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
	unproject(xyz, opts) {
		const viewports = this.getViewports();
		const pixel = {
			x: xyz[0],
			y: xyz[1]
		};
		for (let i = viewports.length - 1; i >= 0; --i) {
			const viewport = viewports[i];
			if (viewport.containsPixel(pixel)) {
				const p = xyz.slice();
				p[0] -= viewport.x;
				p[1] -= viewport.y;
				return viewport.unproject(p, opts);
			}
		}
		return null;
	}
	/** Update the manager with new Deck props */
	setProps(props) {
		if (props.views) this._setViews(props.views);
		if (props.viewState) this._setViewState(props.viewState);
		if ("width" in props || "height" in props) this._setSize(props.width, props.height);
		if ("pickPosition" in props) this._pickPosition = props.pickPosition;
		if (!this._isUpdating) this._update();
	}
	_update() {
		this._isUpdating = true;
		if (this._needsUpdate) {
			this._needsUpdate = false;
			this._rebuildViewports();
		}
		if (this._needsUpdate) {
			this._needsUpdate = false;
			this._rebuildViewports();
		}
		this._isUpdating = false;
	}
	_setSize(width, height) {
		if (width !== this.width || height !== this.height) {
			this.width = width;
			this.height = height;
			this.setNeedsUpdate("Size changed");
		}
	}
	_setViews(views) {
		views = flatten(views, Boolean);
		if (this._diffViews(views, this.views)) this.setNeedsUpdate("views changed");
		this.views = views;
	}
	_setViewState(viewState) {
		if (viewState) {
			if (!deepEqual(viewState, this.viewState, 3)) this.setNeedsUpdate("viewState changed");
			this.viewState = viewState;
		} else defaultLogger.warn("missing `viewState` or `initialViewState`")();
	}
	_createController(view, props) {
		const Controller = props.type;
		return new Controller({
			timeline: this.timeline,
			eventManager: this._eventManager,
			onViewStateChange: this._eventCallbacks.onViewStateChange,
			onStateChange: this._eventCallbacks.onInteractionStateChange,
			makeViewport: (viewState) => this.getView(view.id)?.makeViewport({
				viewState,
				width: this.width,
				height: this.height
			}),
			pickPosition: this._pickPosition
		});
	}
	_updateController(view, viewState, viewport, controller) {
		const controllerProps = view.controller;
		if (controllerProps && viewport) {
			const resolvedProps = {
				...viewState,
				...controllerProps,
				id: view.id,
				x: viewport.x,
				y: viewport.y,
				width: viewport.width,
				height: viewport.height
			};
			if (!controller || controller.constructor !== controllerProps.type) controller = this._createController(view, resolvedProps);
			if (controller) controller.setProps(resolvedProps);
			return controller;
		}
		return null;
	}
	_rebuildViewports() {
		const { views } = this;
		const oldControllers = this.controllers;
		this._viewports = [];
		this.controllers = {};
		let invalidateControllers = false;
		for (let i = views.length; i--;) {
			const view = views[i];
			const viewState = this.getViewState(view);
			const viewport = view.makeViewport({
				viewState,
				width: this.width,
				height: this.height
			});
			let oldController = oldControllers[view.id];
			const hasController = Boolean(view.controller);
			if (hasController && !oldController) invalidateControllers = true;
			if ((invalidateControllers || !hasController) && oldController) {
				oldController.finalize();
				oldController = null;
			}
			this.controllers[view.id] = this._updateController(view, viewState, viewport, oldController);
			if (viewport) this._viewports.unshift(viewport);
		}
		for (const id in oldControllers) {
			const oldController = oldControllers[id];
			if (oldController && !this.controllers[id]) oldController.finalize();
		}
		this._buildViewportMap();
	}
	_buildViewportMap() {
		this._viewportMap = {};
		this._viewports.forEach((viewport) => {
			if (viewport.id) this._viewportMap[viewport.id] = this._viewportMap[viewport.id] || viewport;
		});
	}
	_diffViews(newViews, oldViews) {
		if (newViews.length !== oldViews.length) return true;
		return newViews.some((_, i) => !newViews[i].equals(oldViews[i]));
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/utils/positions.js
var NUMBER_REGEX = /^(?:\d+\.?\d*|\.\d+)$/;
function parsePosition(value) {
	switch (typeof value) {
		case "number":
			if (!Number.isFinite(value)) throw new Error(`Could not parse position string ${value}`);
			return {
				type: "literal",
				value
			};
		case "string": try {
			return new LayoutExpressionParser(tokenize(value)).parseExpression();
		} catch (error) {
			const reason = error instanceof Error ? error.message : String(error);
			throw new Error(`Could not parse position string ${value}: ${reason}`);
		}
		default: throw new Error(`Could not parse position string ${value}`);
	}
}
function evaluateLayoutExpression(expression, extent) {
	switch (expression.type) {
		case "literal": return expression.value;
		case "percentage": return Math.round(expression.value * extent);
		case "binary":
			const left = evaluateLayoutExpression(expression.left, extent);
			const right = evaluateLayoutExpression(expression.right, extent);
			return expression.operator === "+" ? left + right : left - right;
		default: throw new Error("Unknown layout expression type");
	}
}
function getPosition(expression, extent) {
	return evaluateLayoutExpression(expression, extent);
}
function tokenize(input) {
	const tokens = [];
	let index = 0;
	while (index < input.length) {
		const char = input[index];
		if (/\s/.test(char)) {
			index++;
			continue;
		}
		if (char === "+" || char === "-" || char === "(" || char === ")" || char === "%") {
			tokens.push({
				type: "symbol",
				value: char
			});
			index++;
			continue;
		}
		if (isDigit(char) || char === ".") {
			const start = index;
			let hasDecimal = char === ".";
			index++;
			while (index < input.length) {
				const next = input[index];
				if (isDigit(next)) {
					index++;
					continue;
				}
				if (next === "." && !hasDecimal) {
					hasDecimal = true;
					index++;
					continue;
				}
				break;
			}
			const numberString = input.slice(start, index);
			if (!NUMBER_REGEX.test(numberString)) throw new Error("Invalid number token");
			tokens.push({
				type: "number",
				value: parseFloat(numberString)
			});
			continue;
		}
		if (isAlpha(char)) {
			const start = index;
			while (index < input.length && isAlpha(input[index])) index++;
			const word = input.slice(start, index).toLowerCase();
			tokens.push({
				type: "word",
				value: word
			});
			continue;
		}
		throw new Error("Invalid token in position string");
	}
	return tokens;
}
var LayoutExpressionParser = class {
	constructor(tokens) {
		this.index = 0;
		this.tokens = tokens;
	}
	parseExpression() {
		const expression = this.parseBinaryExpression();
		if (this.index < this.tokens.length) throw new Error("Unexpected token at end of expression");
		return expression;
	}
	parseBinaryExpression() {
		let expression = this.parseFactor();
		let token = this.peek();
		while (isAddSubSymbol(token)) {
			this.index++;
			const right = this.parseFactor();
			expression = {
				type: "binary",
				operator: token.value,
				left: expression,
				right
			};
			token = this.peek();
		}
		return expression;
	}
	parseFactor() {
		const token = this.peek();
		if (!token) throw new Error("Unexpected end of expression");
		if (token.type === "symbol" && token.value === "+") {
			this.index++;
			return this.parseFactor();
		}
		if (token.type === "symbol" && token.value === "-") {
			this.index++;
			return {
				type: "binary",
				operator: "-",
				left: {
					type: "literal",
					value: 0
				},
				right: this.parseFactor()
			};
		}
		if (token.type === "symbol" && token.value === "(") {
			this.index++;
			const expression = this.parseBinaryExpression();
			if (!this.consumeSymbol(")")) throw new Error("Missing closing parenthesis");
			return expression;
		}
		if (token.type === "word" && token.value === "calc") {
			this.index++;
			if (!this.consumeSymbol("(")) throw new Error("Missing opening parenthesis after calc");
			const expression = this.parseBinaryExpression();
			if (!this.consumeSymbol(")")) throw new Error("Missing closing parenthesis");
			return expression;
		}
		if (token.type === "number") {
			this.index++;
			const numberValue = token.value;
			const nextToken = this.peek();
			if (nextToken && nextToken.type === "symbol" && nextToken.value === "%") {
				this.index++;
				return {
					type: "percentage",
					value: numberValue / 100
				};
			}
			if (nextToken && nextToken.type === "word" && nextToken.value === "px") {
				this.index++;
				return {
					type: "literal",
					value: numberValue
				};
			}
			return {
				type: "literal",
				value: numberValue
			};
		}
		throw new Error("Unexpected token in expression");
	}
	consumeSymbol(value) {
		const token = this.peek();
		if (token && token.type === "symbol" && token.value === value) {
			this.index++;
			return true;
		}
		return false;
	}
	peek() {
		return this.tokens[this.index] || null;
	}
};
function isDigit(char) {
	return char >= "0" && char <= "9";
}
function isAlpha(char) {
	return char >= "a" && char <= "z" || char >= "A" && char <= "Z";
}
function isAddSubSymbol(token) {
	return Boolean(token && token.type === "symbol" && (token.value === "+" || token.value === "-"));
}
//#endregion
//#region node_modules/@deck.gl/core/dist/utils/deep-merge.js
/** Merge two viewstates, except `id`
* For position arrays such as `target`, only override the components that are defined.
*/
function deepMergeViewState(a, b) {
	const result = { ...a };
	for (const key in b) {
		if (key === "id") continue;
		if (Array.isArray(result[key]) && Array.isArray(b[key])) result[key] = mergeNumericArray(result[key], b[key]);
		else result[key] = b[key];
	}
	return result;
}
function mergeNumericArray(target, source) {
	target = target.slice();
	for (let i = 0; i < source.length; i++) {
		const v = source[i];
		if (Number.isFinite(v)) target[i] = v;
	}
	return target;
}
//#endregion
//#region node_modules/@deck.gl/core/dist/views/view.js
var View = class {
	constructor(props) {
		const { id, x = 0, y = 0, width = "100%", height = "100%", padding = null } = props;
		this.id = id || this.constructor.displayName || "view";
		this.props = {
			...props,
			id: this.id
		};
		this._x = parsePosition(x);
		this._y = parsePosition(y);
		this._width = parsePosition(width);
		this._height = parsePosition(height);
		this._padding = padding && {
			left: parsePosition(padding.left || 0),
			right: parsePosition(padding.right || 0),
			top: parsePosition(padding.top || 0),
			bottom: parsePosition(padding.bottom || 0)
		};
		this.equals = this.equals.bind(this);
		Object.seal(this);
	}
	equals(view) {
		if (this === view) return true;
		return this.constructor === view.constructor && deepEqual(this.props, view.props, 2);
	}
	/** Clone this view with modified props */
	clone(newProps) {
		const ViewConstructor = this.constructor;
		return new ViewConstructor({
			...this.props,
			...newProps
		});
	}
	/** Make viewport from canvas dimensions and view state */
	makeViewport({ width, height, viewState }) {
		viewState = this.filterViewState(viewState);
		const viewportDimensions = this.getDimensions({
			width,
			height
		});
		if (!viewportDimensions.height || !viewportDimensions.width) return null;
		return new (this.getViewportType(viewState))({
			...viewState,
			...this.props,
			...viewportDimensions
		});
	}
	getViewStateId() {
		const { viewState } = this.props;
		if (typeof viewState === "string") return viewState;
		return viewState?.id || this.id;
	}
	filterViewState(viewState) {
		if (this.props.viewState && typeof this.props.viewState === "object") {
			if (!this.props.viewState.id) return this.props.viewState;
			return deepMergeViewState(viewState, this.props.viewState);
		}
		return viewState;
	}
	/** Resolve the dimensions of the view from overall canvas dimensions */
	getDimensions({ width, height }) {
		const dimensions = {
			x: getPosition(this._x, width),
			y: getPosition(this._y, height),
			width: getPosition(this._width, width),
			height: getPosition(this._height, height)
		};
		if (this._padding) dimensions.padding = {
			left: getPosition(this._padding.left, width),
			top: getPosition(this._padding.top, height),
			right: getPosition(this._padding.right, width),
			bottom: getPosition(this._padding.bottom, height)
		};
		return dimensions;
	}
	get controller() {
		const opts = this.props.controller;
		if (!opts) return null;
		if (opts === true) return { type: this.ControllerType };
		if (typeof opts === "function") return { type: opts };
		return {
			type: this.ControllerType,
			...opts
		};
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/controllers/transition-manager.js
var noop$1 = () => {};
var TRANSITION_EVENTS = {
	BREAK: 1,
	SNAP_TO_END: 2,
	IGNORE: 3
};
var DEFAULT_EASING = (t) => t;
var DEFAULT_INTERRUPTION = TRANSITION_EVENTS.BREAK;
var TransitionManager = class {
	constructor(opts) {
		this._onTransitionUpdate = (transition) => {
			const { time, settings: { interpolator, startProps, endProps, duration, easing } } = transition;
			const t = easing(time / duration);
			const viewport = interpolator.interpolateProps(startProps, endProps, t);
			this.propsInTransition = this.getControllerState({
				...this.props,
				...viewport
			}).getViewportProps();
			this.onViewStateChange({
				viewState: this.propsInTransition,
				oldViewState: this.props
			});
		};
		this.getControllerState = opts.getControllerState;
		this.propsInTransition = null;
		this.transition = new Transition(opts.timeline);
		this.onViewStateChange = opts.onViewStateChange || noop$1;
		this.onStateChange = opts.onStateChange || noop$1;
	}
	finalize() {
		this.transition.cancel();
	}
	getViewportInTransition() {
		return this.propsInTransition;
	}
	processViewStateChange(nextProps) {
		let transitionTriggered = false;
		const currentProps = this.props;
		this.props = nextProps;
		if (!currentProps || this._shouldIgnoreViewportChange(currentProps, nextProps)) return false;
		if (this._isTransitionEnabled(nextProps)) {
			let startProps = currentProps;
			if (this.transition.inProgress) {
				const { interruption, endProps } = this.transition.settings;
				startProps = {
					...currentProps,
					...interruption === TRANSITION_EVENTS.SNAP_TO_END ? endProps : this.propsInTransition || currentProps
				};
			}
			this._triggerTransition(startProps, nextProps);
			transitionTriggered = true;
		} else this.transition.cancel();
		return transitionTriggered;
	}
	updateTransition() {
		this.transition.update();
	}
	_isTransitionEnabled(props) {
		const { transitionDuration, transitionInterpolator } = props;
		return (transitionDuration > 0 || transitionDuration === "auto") && Boolean(transitionInterpolator);
	}
	_isUpdateDueToCurrentTransition(props) {
		if (this.transition.inProgress && this.propsInTransition) return this.transition.settings.interpolator.arePropsEqual(props, this.propsInTransition);
		return false;
	}
	_shouldIgnoreViewportChange(currentProps, nextProps) {
		if (this.transition.inProgress) return this.transition.settings.interruption === TRANSITION_EVENTS.IGNORE || this._isUpdateDueToCurrentTransition(nextProps);
		if (this._isTransitionEnabled(nextProps)) return nextProps.transitionInterpolator.arePropsEqual(currentProps, nextProps);
		return true;
	}
	_triggerTransition(startProps, endProps) {
		const startViewstate = this.getControllerState(startProps);
		const endViewStateProps = this.getControllerState(endProps).shortestPathFrom(startViewstate);
		const transitionInterpolator = endProps.transitionInterpolator;
		const duration = transitionInterpolator.getDuration ? transitionInterpolator.getDuration(startProps, endProps) : endProps.transitionDuration;
		if (duration === 0) return;
		const initialProps = transitionInterpolator.initializeProps(startProps, endViewStateProps);
		this.propsInTransition = {};
		const transitionSettings = {
			duration,
			easing: endProps.transitionEasing || DEFAULT_EASING,
			interpolator: transitionInterpolator,
			interruption: endProps.transitionInterruption || DEFAULT_INTERRUPTION,
			startProps: initialProps.start,
			endProps: initialProps.end,
			onStart: endProps.onTransitionStart,
			onUpdate: this._onTransitionUpdate,
			onInterrupt: this._onTransitionEnd(endProps.onTransitionInterrupt),
			onEnd: this._onTransitionEnd(endProps.onTransitionEnd)
		};
		this.transition.start(transitionSettings);
		this.onStateChange({ inTransition: true });
		this.updateTransition();
	}
	_onTransitionEnd(callback) {
		return (transition) => {
			this.propsInTransition = null;
			this.onStateChange({
				inTransition: false,
				isZooming: false,
				isPanning: false,
				isRotating: false
			});
			callback?.(transition);
		};
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/transitions/transition-interpolator.js
var TransitionInterpolator = class {
	/**
	* @param opts {array|object}
	* @param opts.compare {array} - prop names used in equality check
	* @param opts.extract {array} - prop names needed for interpolation
	* @param opts.required {array} - prop names that must be supplied
	* alternatively, supply one list of prop names as `opts` if all of the above are the same.
	*/
	constructor(opts) {
		const { compare, extract, required } = opts;
		this._propsToCompare = compare;
		this._propsToExtract = extract || compare;
		this._requiredProps = required;
	}
	/**
	* Checks if two sets of props need transition in between
	* @param currentProps {object} - a list of viewport props
	* @param nextProps {object} - a list of viewport props
	* @returns {bool} - true if two props are equivalent
	*/
	arePropsEqual(currentProps, nextProps) {
		for (const key of this._propsToCompare) if (!(key in currentProps) || !(key in nextProps) || !equals(currentProps[key], nextProps[key])) return false;
		return true;
	}
	/**
	* Called before transition starts to validate/pre-process start and end props
	* @param startProps {object} - a list of starting viewport props
	* @param endProps {object} - a list of target viewport props
	* @returns {Object} {start, end} - start and end props to be passed
	*   to `interpolateProps`
	*/
	initializeProps(startProps, endProps) {
		const startViewStateProps = {};
		const endViewStateProps = {};
		for (const key of this._propsToExtract) if (key in startProps || key in endProps) {
			startViewStateProps[key] = startProps[key];
			endViewStateProps[key] = endProps[key];
		}
		this._checkRequiredProps(startViewStateProps);
		this._checkRequiredProps(endViewStateProps);
		return {
			start: startViewStateProps,
			end: endViewStateProps
		};
	}
	/**
	* Returns transition duration
	* @param startProps {object} - a list of starting viewport props
	* @param endProps {object} - a list of target viewport props
	* @returns {Number} - transition duration in milliseconds
	*/
	getDuration(startProps, endProps) {
		return endProps.transitionDuration;
	}
	_checkRequiredProps(props) {
		if (!this._requiredProps) return;
		this._requiredProps.forEach((propName) => {
			const value = props[propName];
			assert$1(Number.isFinite(value) || Array.isArray(value), `${propName} is required for transition`);
		});
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/viewports/globe-viewport.js
var DEGREES_TO_RADIANS$2 = Math.PI / 180;
var RADIANS_TO_DEGREES$1 = 180 / Math.PI;
var EARTH_RADIUS = 6370972;
function getDistanceScales() {
	const unitsPerMeter = 256 / EARTH_RADIUS;
	const unitsPerDegree = Math.PI / 180 * 256;
	return {
		unitsPerMeter: [
			unitsPerMeter,
			unitsPerMeter,
			unitsPerMeter
		],
		unitsPerMeter2: [
			0,
			0,
			0
		],
		metersPerUnit: [
			1 / unitsPerMeter,
			1 / unitsPerMeter,
			1 / unitsPerMeter
		],
		unitsPerDegree: [
			unitsPerDegree,
			unitsPerDegree,
			unitsPerMeter
		],
		unitsPerDegree2: [
			0,
			0,
			0
		],
		degreesPerUnit: [
			1 / unitsPerDegree,
			1 / unitsPerDegree,
			1 / unitsPerMeter
		]
	};
}
var GlobeViewport = class extends Viewport {
	constructor(opts = {}) {
		const { longitude = 0, zoom = 0, nearZMultiplier = .5, farZMultiplier = 1, resolution = 10 } = opts;
		let { latitude = 0, height, altitude = 1.5, fovy } = opts;
		latitude = Math.max(Math.min(latitude, MAX_LATITUDE), -MAX_LATITUDE);
		height = height || 1;
		if (fovy) altitude = fovyToAltitude(fovy);
		else fovy = altitudeToFovy(altitude);
		const scale = Math.pow(2, zoom - zoomAdjust(latitude));
		const nearZ = opts.nearZ ?? nearZMultiplier;
		const farZ = opts.farZ ?? (altitude + 256 * 2 * scale / height) * farZMultiplier;
		const viewMatrix = new Matrix4().lookAt({
			eye: [
				0,
				-altitude,
				0
			],
			up: [
				0,
				0,
				1
			]
		});
		viewMatrix.rotateX(latitude * DEGREES_TO_RADIANS$2);
		viewMatrix.rotateZ(-longitude * DEGREES_TO_RADIANS$2);
		viewMatrix.scale(scale / height);
		super({
			...opts,
			height,
			viewMatrix,
			longitude,
			latitude,
			zoom,
			distanceScales: getDistanceScales(),
			fovy,
			focalDistance: altitude,
			near: nearZ,
			far: farZ
		});
		this.scale = scale;
		this.latitude = latitude;
		this.longitude = longitude;
		this.fovy = fovy;
		this.resolution = resolution;
	}
	get projectionMode() {
		return PROJECTION_MODE.GLOBE;
	}
	getDistanceScales() {
		return this.distanceScales;
	}
	getBounds(options = {}) {
		const unprojectOption = { targetZ: options.z || 0 };
		const left = this.unproject([0, this.height / 2], unprojectOption);
		const top = this.unproject([this.width / 2, 0], unprojectOption);
		const right = this.unproject([this.width, this.height / 2], unprojectOption);
		const bottom = this.unproject([this.width / 2, this.height], unprojectOption);
		if (right[0] < this.longitude) right[0] += 360;
		if (left[0] > this.longitude) left[0] -= 360;
		return [
			Math.min(left[0], right[0], top[0], bottom[0]),
			Math.min(left[1], right[1], top[1], bottom[1]),
			Math.max(left[0], right[0], top[0], bottom[0]),
			Math.max(left[1], right[1], top[1], bottom[1])
		];
	}
	unproject(xyz, { topLeft = true, targetZ } = {}) {
		const [x, y, z] = xyz;
		const y2 = topLeft ? y : this.height - y;
		const { pixelUnprojectionMatrix } = this;
		let coord;
		if (Number.isFinite(z)) coord = transformVector(pixelUnprojectionMatrix, [
			x,
			y2,
			z,
			1
		]);
		else {
			const coord0 = transformVector(pixelUnprojectionMatrix, [
				x,
				y2,
				-1,
				1
			]);
			const coord1 = transformVector(pixelUnprojectionMatrix, [
				x,
				y2,
				1,
				1
			]);
			const lt = ((targetZ || 0) / EARTH_RADIUS + 1) * 256;
			const lSqr = sqrLen(sub([], coord0, coord1));
			const l0Sqr = sqrLen(coord0);
			const l1Sqr = sqrLen(coord1);
			const dSqr = 4 * ((4 * l0Sqr * l1Sqr - (lSqr - l0Sqr - l1Sqr) ** 2) / 16) / lSqr;
			coord = lerp([], coord0, coord1, (Math.sqrt(l0Sqr - dSqr) - Math.sqrt(Math.max(0, lt * lt - dSqr))) / Math.sqrt(lSqr));
		}
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
		const [lng, lat, Z = 0] = xyz;
		const lambda = lng * DEGREES_TO_RADIANS$2;
		const phi = lat * DEGREES_TO_RADIANS$2;
		const cosPhi = Math.cos(phi);
		const D = (Z / EARTH_RADIUS + 1) * 256;
		return [
			Math.sin(lambda) * cosPhi * D,
			-Math.cos(lambda) * cosPhi * D,
			Math.sin(phi) * D
		];
	}
	unprojectPosition(xyz) {
		const [x, y, z] = xyz;
		const D = len(xyz);
		const phi = Math.asin(z / D);
		return [
			Math.atan2(x, -y) * RADIANS_TO_DEGREES$1,
			phi * RADIANS_TO_DEGREES$1,
			(D / 256 - 1) * EARTH_RADIUS
		];
	}
	projectFlat(xyz) {
		return xyz;
	}
	unprojectFlat(xyz) {
		return xyz;
	}
	/**
	* Pan the globe using delta-based movement
	* @param coords - the geographic coordinates where the pan started
	* @param pixel - the current screen position
	* @param startPixel - the screen position where the pan started
	* @returns updated viewport options with new longitude/latitude
	*/
	panByPosition([startLng, startLat, startZoom], pixel, startPixel) {
		const rotationSpeed = .25 / Math.pow(2, this.zoom - zoomAdjust(this.latitude));
		const longitude = startLng + rotationSpeed * (startPixel[0] - pixel[0]);
		let latitude = startLat - rotationSpeed * (startPixel[1] - pixel[1]);
		latitude = Math.max(Math.min(latitude, MAX_LATITUDE), -MAX_LATITUDE);
		const out = {
			longitude,
			latitude,
			zoom: startZoom - zoomAdjust(startLat)
		};
		out.zoom += zoomAdjust(out.latitude);
		return out;
	}
};
GlobeViewport.displayName = "GlobeViewport";
function zoomAdjust(latitude) {
	const scaleAdjust = Math.PI * Math.cos(latitude * Math.PI / 180);
	return Math.log2(scaleAdjust);
}
function transformVector(matrix, vector) {
	const result = transformMat4([], vector, matrix);
	scale(result, result, 1 / result[3]);
	return result;
}
//#endregion
//#region node_modules/@deck.gl/core/dist/transitions/linear-interpolator.js
var DEFAULT_PROPS = [
	"longitude",
	"latitude",
	"zoom",
	"bearing",
	"pitch"
];
var DEFAULT_REQUIRED_PROPS = [
	"longitude",
	"latitude",
	"zoom"
];
/**
* Performs linear interpolation of two view states.
*/
var LinearInterpolator = class extends TransitionInterpolator {
	/**
	* @param {Object} opts
	* @param {Array} opts.transitionProps - list of props to apply linear transition to.
	* @param {Array} opts.around - a screen point to zoom/rotate around.
	* @param {Function} opts.makeViewport - construct a viewport instance with given props.
	*/
	constructor(opts = {}) {
		const transitionProps = Array.isArray(opts) ? opts : opts.transitionProps;
		const normalizedOpts = Array.isArray(opts) ? {} : opts;
		normalizedOpts.transitionProps = Array.isArray(transitionProps) ? {
			compare: transitionProps,
			required: transitionProps
		} : transitionProps || {
			compare: DEFAULT_PROPS,
			required: DEFAULT_REQUIRED_PROPS
		};
		super(normalizedOpts.transitionProps);
		this.opts = normalizedOpts;
	}
	initializeProps(startProps, endProps) {
		const result = super.initializeProps(startProps, endProps);
		const { makeViewport, around } = this.opts;
		if (makeViewport && around) if (makeViewport(startProps) instanceof GlobeViewport) defaultLogger.warn("around not supported in GlobeView")();
		else {
			const startViewport = makeViewport(startProps);
			const endViewport = makeViewport(endProps);
			const aroundPosition = startViewport.unproject(around);
			result.start.around = around;
			Object.assign(result.end, {
				around: endViewport.project(aroundPosition),
				aroundPosition,
				width: endProps.width,
				height: endProps.height
			});
		}
		return result;
	}
	interpolateProps(startProps, endProps, t) {
		const propsInTransition = {};
		for (const key of this._propsToExtract) propsInTransition[key] = lerp$1(startProps[key] || 0, endProps[key] || 0, t);
		if (endProps.aroundPosition && this.opts.makeViewport) {
			const viewport = this.opts.makeViewport({
				...endProps,
				...propsInTransition
			});
			Object.assign(propsInTransition, viewport.panByPosition(endProps.aroundPosition, lerp$1(startProps.around, endProps.around, t)));
		}
		return propsInTransition;
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/controllers/controller.js
var NO_TRANSITION_PROPS = { transitionDuration: 0 };
var DEFAULT_INERTIA = 300;
var INERTIA_EASING = (t) => 1 - (1 - t) * (1 - t);
var EVENT_TYPES = {
	WHEEL: ["wheel"],
	PAN: [
		"panstart",
		"panmove",
		"panend"
	],
	PINCH: [
		"pinchstart",
		"pinchmove",
		"pinchend"
	],
	MULTI_PAN: [
		"multipanstart",
		"multipanmove",
		"multipanend"
	],
	DOUBLE_CLICK: ["dblclick"],
	KEYBOARD: ["keydown"]
};
var pinchEventWorkaround = {};
var Controller = class {
	constructor(opts) {
		this.state = {};
		this._events = {};
		this._interactionState = { isDragging: false };
		this._customEvents = [];
		this._eventStartBlocked = null;
		this._panMove = false;
		this.invertPan = false;
		this.dragMode = "rotate";
		this.inertia = 0;
		this.scrollZoom = true;
		this.dragPan = true;
		this.dragRotate = true;
		this.doubleClickZoom = true;
		this.touchZoom = true;
		this.touchRotate = false;
		this.keyboard = true;
		this.transitionManager = new TransitionManager({
			...opts,
			getControllerState: (props) => new this.ControllerState(props),
			onViewStateChange: this._onTransition.bind(this),
			onStateChange: this._setInteractionState.bind(this)
		});
		this.handleEvent = this.handleEvent.bind(this);
		this.eventManager = opts.eventManager;
		this.onViewStateChange = opts.onViewStateChange || (() => {});
		this.onStateChange = opts.onStateChange || (() => {});
		this.makeViewport = opts.makeViewport;
		this.pickPosition = opts.pickPosition;
	}
	set events(customEvents) {
		this.toggleEvents(this._customEvents, false);
		this.toggleEvents(customEvents, true);
		this._customEvents = customEvents;
		if (this.props) this.setProps(this.props);
	}
	finalize() {
		for (const eventName in this._events) if (this._events[eventName]) this.eventManager?.off(eventName, this.handleEvent);
		this.transitionManager.finalize();
	}
	/**
	* Callback for events
	*/
	handleEvent(event) {
		this._controllerState = void 0;
		const eventStartBlocked = this._eventStartBlocked;
		switch (event.type) {
			case "panstart": return eventStartBlocked ? false : this._onPanStart(event);
			case "panmove": return this._onPan(event);
			case "panend": return this._onPanEnd(event);
			case "pinchstart": return eventStartBlocked ? false : this._onPinchStart(event);
			case "pinchmove": return this._onPinch(event);
			case "pinchend": return this._onPinchEnd(event);
			case "multipanstart": return eventStartBlocked ? false : this._onMultiPanStart(event);
			case "multipanmove": return this._onMultiPan(event);
			case "multipanend": return this._onMultiPanEnd(event);
			case "dblclick": return this._onDoubleClick(event);
			case "wheel": return this._onWheel(event);
			case "keydown": return this._onKeyDown(event);
			default: return false;
		}
	}
	get controllerState() {
		this._controllerState = this._controllerState || new this.ControllerState({
			makeViewport: this.makeViewport,
			...this.props,
			...this.state
		});
		return this._controllerState;
	}
	getCenter(event) {
		const { x, y } = this.props;
		const { offsetCenter } = event;
		return [offsetCenter.x - x, offsetCenter.y - y];
	}
	isPointInBounds(pos, event) {
		const { width, height } = this.props;
		if (event && event.handled) return false;
		const inside = pos[0] >= 0 && pos[0] <= width && pos[1] >= 0 && pos[1] <= height;
		if (inside && event) event.stopPropagation();
		return inside;
	}
	isFunctionKeyPressed(event) {
		const { srcEvent } = event;
		return Boolean(srcEvent.metaKey || srcEvent.altKey || srcEvent.ctrlKey || srcEvent.shiftKey);
	}
	isDragging() {
		return this._interactionState.isDragging || false;
	}
	blockEvents(timeout) {
		const timer = setTimeout(() => {
			if (this._eventStartBlocked === timer) this._eventStartBlocked = null;
		}, timeout);
		this._eventStartBlocked = timer;
	}
	/**
	* Extract interactivity options
	*/
	setProps(props) {
		if (props.dragMode) this.dragMode = props.dragMode;
		const oldProps = this.props;
		this.props = props;
		if (!("transitionInterpolator" in props)) props.transitionInterpolator = this._getTransitionProps().transitionInterpolator;
		this.transitionManager.processViewStateChange(props);
		const { inertia } = props;
		this.inertia = Number.isFinite(inertia) ? inertia : inertia === true ? DEFAULT_INERTIA : 0;
		const { scrollZoom = true, dragPan = true, dragRotate = true, doubleClickZoom = true, touchZoom = true, touchRotate = false, keyboard = true } = props;
		const isInteractive = Boolean(this.onViewStateChange);
		this.toggleEvents(EVENT_TYPES.WHEEL, isInteractive && scrollZoom);
		this.toggleEvents(EVENT_TYPES.PAN, isInteractive);
		this.toggleEvents(EVENT_TYPES.PINCH, isInteractive && (touchZoom || touchRotate));
		this.toggleEvents(EVENT_TYPES.MULTI_PAN, isInteractive && touchRotate);
		this.toggleEvents(EVENT_TYPES.DOUBLE_CLICK, isInteractive && doubleClickZoom);
		this.toggleEvents(EVENT_TYPES.KEYBOARD, isInteractive && keyboard);
		this.scrollZoom = scrollZoom;
		this.dragPan = dragPan;
		this.dragRotate = dragRotate;
		this.doubleClickZoom = doubleClickZoom;
		this.touchZoom = touchZoom;
		this.touchRotate = touchRotate;
		this.keyboard = keyboard;
		if ((!oldProps || oldProps.height !== props.height || oldProps.width !== props.width || oldProps.maxBounds !== props.maxBounds) && props.maxBounds) {
			const controllerState = new this.ControllerState({
				...props,
				makeViewport: this.makeViewport
			});
			const normalizedProps = controllerState.getViewportProps();
			if (Object.keys(normalizedProps).some((key) => !deepEqual(normalizedProps[key], props[key], 1))) this.updateViewport(controllerState);
		}
	}
	updateTransition() {
		this.transitionManager.updateTransition();
	}
	toggleEvents(eventNames, enabled) {
		if (this.eventManager) eventNames.forEach((eventName) => {
			if (this._events[eventName] !== enabled) {
				this._events[eventName] = enabled;
				if (enabled) this.eventManager.on(eventName, this.handleEvent);
				else this.eventManager.off(eventName, this.handleEvent);
			}
		});
	}
	updateViewport(newControllerState, extraProps = null, interactionState = {}) {
		const viewState = {
			...newControllerState.getViewportProps(),
			...extraProps
		};
		const changed = this.controllerState !== newControllerState;
		this.state = newControllerState.getState();
		this._setInteractionState(interactionState);
		if (changed) {
			const oldViewState = this.controllerState && this.controllerState.getViewportProps();
			if (this.onViewStateChange) this.onViewStateChange({
				viewState,
				interactionState: this._interactionState,
				oldViewState,
				viewId: this.props.id
			});
		}
	}
	_onTransition(params) {
		this.onViewStateChange({
			...params,
			interactionState: this._interactionState,
			viewId: this.props.id
		});
	}
	_setInteractionState(newStates) {
		Object.assign(this._interactionState, newStates);
		this.onStateChange(this._interactionState);
	}
	_onPanStart(event) {
		const pos = this.getCenter(event);
		if (!this.isPointInBounds(pos, event)) return false;
		let alternateMode = this.isFunctionKeyPressed(event) || event.rightButton || false;
		if (this.invertPan || this.dragMode === "pan") alternateMode = !alternateMode;
		const newControllerState = this.controllerState[alternateMode ? "panStart" : "rotateStart"]({ pos });
		this._panMove = alternateMode;
		this.updateViewport(newControllerState, NO_TRANSITION_PROPS, { isDragging: true });
		return true;
	}
	_onPan(event) {
		if (!this.isDragging()) return false;
		return this._panMove ? this._onPanMove(event) : this._onPanRotate(event);
	}
	_onPanEnd(event) {
		if (!this.isDragging()) return false;
		return this._panMove ? this._onPanMoveEnd(event) : this._onPanRotateEnd(event);
	}
	_onPanMove(event) {
		if (!this.dragPan) return false;
		const pos = this.getCenter(event);
		const newControllerState = this.controllerState.pan({ pos });
		this.updateViewport(newControllerState, NO_TRANSITION_PROPS, {
			isDragging: true,
			isPanning: true
		});
		return true;
	}
	_onPanMoveEnd(event) {
		const { inertia } = this;
		if (this.dragPan && inertia && event.velocity) {
			const pos = this.getCenter(event);
			const endPos = [pos[0] + event.velocityX * inertia / 2, pos[1] + event.velocityY * inertia / 2];
			const newControllerState = this.controllerState.pan({ pos: endPos }).panEnd();
			this.updateViewport(newControllerState, {
				...this._getTransitionProps(),
				transitionDuration: inertia,
				transitionEasing: INERTIA_EASING
			}, {
				isDragging: false,
				isPanning: true
			});
		} else {
			const newControllerState = this.controllerState.panEnd();
			this.updateViewport(newControllerState, null, {
				isDragging: false,
				isPanning: false
			});
		}
		return true;
	}
	_onPanRotate(event) {
		if (!this.dragRotate) return false;
		const pos = this.getCenter(event);
		const newControllerState = this.controllerState.rotate({ pos });
		this.updateViewport(newControllerState, NO_TRANSITION_PROPS, {
			isDragging: true,
			isRotating: true
		});
		return true;
	}
	_onPanRotateEnd(event) {
		const { inertia } = this;
		if (this.dragRotate && inertia && event.velocity) {
			const pos = this.getCenter(event);
			const endPos = [pos[0] + event.velocityX * inertia / 2, pos[1] + event.velocityY * inertia / 2];
			const newControllerState = this.controllerState.rotate({ pos: endPos }).rotateEnd();
			this.updateViewport(newControllerState, {
				...this._getTransitionProps(),
				transitionDuration: inertia,
				transitionEasing: INERTIA_EASING
			}, {
				isDragging: false,
				isRotating: true
			});
		} else {
			const newControllerState = this.controllerState.rotateEnd();
			this.updateViewport(newControllerState, null, {
				isDragging: false,
				isRotating: false
			});
		}
		return true;
	}
	_onWheel(event) {
		if (!this.scrollZoom) return false;
		const pos = this.getCenter(event);
		if (!this.isPointInBounds(pos, event)) return false;
		event.srcEvent.preventDefault();
		const { speed = .01, smooth = false } = this.scrollZoom === true ? {} : this.scrollZoom;
		const { delta } = event;
		let scale = 2 / (1 + Math.exp(-Math.abs(delta * speed)));
		if (delta < 0 && scale !== 0) scale = 1 / scale;
		const transitionProps = smooth ? {
			...this._getTransitionProps({ around: pos }),
			transitionDuration: 250
		} : NO_TRANSITION_PROPS;
		const newControllerState = this.controllerState.zoom({
			pos,
			scale
		});
		this.updateViewport(newControllerState, transitionProps, {
			isZooming: true,
			isPanning: true
		});
		if (!smooth) this._setInteractionState({
			isZooming: false,
			isPanning: false
		});
		return true;
	}
	_onMultiPanStart(event) {
		const pos = this.getCenter(event);
		if (!this.isPointInBounds(pos, event)) return false;
		const newControllerState = this.controllerState.rotateStart({ pos });
		this.updateViewport(newControllerState, NO_TRANSITION_PROPS, { isDragging: true });
		return true;
	}
	_onMultiPan(event) {
		if (!this.touchRotate) return false;
		if (!this.isDragging()) return false;
		const pos = this.getCenter(event);
		pos[0] -= event.deltaX;
		const newControllerState = this.controllerState.rotate({ pos });
		this.updateViewport(newControllerState, NO_TRANSITION_PROPS, {
			isDragging: true,
			isRotating: true
		});
		return true;
	}
	_onMultiPanEnd(event) {
		if (!this.isDragging()) return false;
		const { inertia } = this;
		if (this.touchRotate && inertia && event.velocityY) {
			const pos = this.getCenter(event);
			const endPos = [pos[0], pos[1] += event.velocityY * inertia / 2];
			const newControllerState = this.controllerState.rotate({ pos: endPos });
			this.updateViewport(newControllerState, {
				...this._getTransitionProps(),
				transitionDuration: inertia,
				transitionEasing: INERTIA_EASING
			}, {
				isDragging: false,
				isRotating: true
			});
			this.blockEvents(inertia);
		} else {
			const newControllerState = this.controllerState.rotateEnd();
			this.updateViewport(newControllerState, null, {
				isDragging: false,
				isRotating: false
			});
		}
		return true;
	}
	_onPinchStart(event) {
		const pos = this.getCenter(event);
		if (!this.isPointInBounds(pos, event)) return false;
		const newControllerState = this.controllerState.zoomStart({ pos }).rotateStart({ pos });
		pinchEventWorkaround._startPinchRotation = event.rotation;
		pinchEventWorkaround._lastPinchEvent = event;
		this.updateViewport(newControllerState, NO_TRANSITION_PROPS, { isDragging: true });
		return true;
	}
	_onPinch(event) {
		if (!this.touchZoom && !this.touchRotate) return false;
		if (!this.isDragging()) return false;
		let newControllerState = this.controllerState;
		if (this.touchZoom) {
			const { scale } = event;
			const pos = this.getCenter(event);
			newControllerState = newControllerState.zoom({
				pos,
				scale
			});
		}
		if (this.touchRotate) {
			const { rotation } = event;
			newControllerState = newControllerState.rotate({ deltaAngleX: pinchEventWorkaround._startPinchRotation - rotation });
		}
		this.updateViewport(newControllerState, NO_TRANSITION_PROPS, {
			isDragging: true,
			isPanning: this.touchZoom,
			isZooming: this.touchZoom,
			isRotating: this.touchRotate
		});
		pinchEventWorkaround._lastPinchEvent = event;
		return true;
	}
	_onPinchEnd(event) {
		if (!this.isDragging()) return false;
		const { inertia } = this;
		const { _lastPinchEvent } = pinchEventWorkaround;
		if (this.touchZoom && inertia && _lastPinchEvent && event.scale !== _lastPinchEvent.scale) {
			const pos = this.getCenter(event);
			let newControllerState = this.controllerState.rotateEnd();
			const z = Math.log2(event.scale);
			const velocityZ = (z - Math.log2(_lastPinchEvent.scale)) / (event.deltaTime - _lastPinchEvent.deltaTime);
			const endScale = Math.pow(2, z + velocityZ * inertia / 2);
			newControllerState = newControllerState.zoom({
				pos,
				scale: endScale
			}).zoomEnd();
			this.updateViewport(newControllerState, {
				...this._getTransitionProps({ around: pos }),
				transitionDuration: inertia,
				transitionEasing: INERTIA_EASING
			}, {
				isDragging: false,
				isPanning: this.touchZoom,
				isZooming: this.touchZoom,
				isRotating: false
			});
			this.blockEvents(inertia);
		} else {
			const newControllerState = this.controllerState.zoomEnd().rotateEnd();
			this.updateViewport(newControllerState, null, {
				isDragging: false,
				isPanning: false,
				isZooming: false,
				isRotating: false
			});
		}
		pinchEventWorkaround._startPinchRotation = null;
		pinchEventWorkaround._lastPinchEvent = null;
		return true;
	}
	_onDoubleClick(event) {
		if (!this.doubleClickZoom) return false;
		const pos = this.getCenter(event);
		if (!this.isPointInBounds(pos, event)) return false;
		const isZoomOut = this.isFunctionKeyPressed(event);
		const newControllerState = this.controllerState.zoom({
			pos,
			scale: isZoomOut ? .5 : 2
		});
		this.updateViewport(newControllerState, this._getTransitionProps({ around: pos }), {
			isZooming: true,
			isPanning: true
		});
		this.blockEvents(100);
		return true;
	}
	_onKeyDown(event) {
		if (!this.keyboard) return false;
		const funcKey = this.isFunctionKeyPressed(event);
		const { zoomSpeed, moveSpeed, rotateSpeedX, rotateSpeedY } = this.keyboard === true ? {} : this.keyboard;
		const { controllerState } = this;
		let newControllerState;
		const interactionState = {};
		switch (event.srcEvent.code) {
			case "Minus":
				newControllerState = funcKey ? controllerState.zoomOut(zoomSpeed).zoomOut(zoomSpeed) : controllerState.zoomOut(zoomSpeed);
				interactionState.isZooming = true;
				break;
			case "Equal":
				newControllerState = funcKey ? controllerState.zoomIn(zoomSpeed).zoomIn(zoomSpeed) : controllerState.zoomIn(zoomSpeed);
				interactionState.isZooming = true;
				break;
			case "ArrowLeft":
				if (funcKey) {
					newControllerState = controllerState.rotateLeft(rotateSpeedX);
					interactionState.isRotating = true;
				} else {
					newControllerState = controllerState.moveLeft(moveSpeed);
					interactionState.isPanning = true;
				}
				break;
			case "ArrowRight":
				if (funcKey) {
					newControllerState = controllerState.rotateRight(rotateSpeedX);
					interactionState.isRotating = true;
				} else {
					newControllerState = controllerState.moveRight(moveSpeed);
					interactionState.isPanning = true;
				}
				break;
			case "ArrowUp":
				if (funcKey) {
					newControllerState = controllerState.rotateUp(rotateSpeedY);
					interactionState.isRotating = true;
				} else {
					newControllerState = controllerState.moveUp(moveSpeed);
					interactionState.isPanning = true;
				}
				break;
			case "ArrowDown":
				if (funcKey) {
					newControllerState = controllerState.rotateDown(rotateSpeedY);
					interactionState.isRotating = true;
				} else {
					newControllerState = controllerState.moveDown(moveSpeed);
					interactionState.isPanning = true;
				}
				break;
			default: return false;
		}
		this.updateViewport(newControllerState, this._getTransitionProps(), interactionState);
		return true;
	}
	_getTransitionProps(opts) {
		const { transition } = this;
		if (!transition || !transition.transitionInterpolator) return NO_TRANSITION_PROPS;
		return opts ? {
			...transition,
			transitionInterpolator: new LinearInterpolator({
				...opts,
				...transition.transitionInterpolator.opts,
				makeViewport: this.controllerState.makeViewport
			})
		} : transition;
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/controllers/view-state.js
var ViewState = class {
	constructor(props, state, makeViewport) {
		this.makeViewport = makeViewport;
		this._viewportProps = this.applyConstraints(props);
		this._state = state;
	}
	getViewportProps() {
		return this._viewportProps;
	}
	getState() {
		return this._state;
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/controllers/map-controller.js
var PITCH_MOUSE_THRESHOLD = 5;
var PITCH_ACCEL = 1.2;
var WEB_MERCATOR_TILE_SIZE = 512;
var WEB_MERCATOR_MAX_BOUNDS = [[-Infinity, -90], [Infinity, 90]];
/** The web mercator utility `lngLatToWorld` throws if invalid coordinates are provided.
* This wrapper clamps user input to calculate common positions safely. */
function lngLatToWorld([lng, lat]) {
	if (Math.abs(lat) > 90) lat = Math.sign(lat) * 90;
	if (Number.isFinite(lng)) {
		const [x, y] = lngLatToWorld$1([lng, lat]);
		return [x, clamp(y, 0, WEB_MERCATOR_TILE_SIZE)];
	}
	const [, y] = lngLatToWorld$1([0, lat]);
	return [lng, clamp(y, 0, WEB_MERCATOR_TILE_SIZE)];
}
var MapState = class extends ViewState {
	constructor(options) {
		const { width, height, latitude, longitude, zoom, bearing = 0, pitch = 0, altitude = 1.5, position = [
			0,
			0,
			0
		], maxZoom = 20, minZoom = 0, maxPitch = 60, minPitch = 0, startPanLngLat, startZoomLngLat, startRotatePos, startRotateLngLat, startBearing, startPitch, startZoom, normalize = true } = options;
		assert$1(Number.isFinite(longitude));
		assert$1(Number.isFinite(latitude));
		assert$1(Number.isFinite(zoom));
		const maxBounds = options.maxBounds || (normalize ? WEB_MERCATOR_MAX_BOUNDS : null);
		super({
			width,
			height,
			latitude,
			longitude,
			zoom,
			bearing,
			pitch,
			altitude,
			maxZoom,
			minZoom,
			maxPitch,
			minPitch,
			normalize,
			position,
			maxBounds
		}, {
			startPanLngLat,
			startZoomLngLat,
			startRotatePos,
			startRotateLngLat,
			startBearing,
			startPitch,
			startZoom
		}, options.makeViewport);
		this.getAltitude = options.getAltitude;
	}
	/**
	* Start panning
	* @param {[Number, Number]} pos - position on screen where the pointer grabs
	*/
	panStart({ pos }) {
		return this._getUpdatedState({ startPanLngLat: this._unproject(pos) });
	}
	/**
	* Pan
	* @param {[Number, Number]} pos - position on screen where the pointer is
	* @param {[Number, Number], optional} startPos - where the pointer grabbed at
	*   the start of the operation. Must be supplied of `panStart()` was not called
	*/
	pan({ pos, startPos }) {
		const startPanLngLat = this.getState().startPanLngLat || this._unproject(startPos);
		if (!startPanLngLat) return this;
		const newProps = this.makeViewport(this.getViewportProps()).panByPosition(startPanLngLat, pos);
		return this._getUpdatedState(newProps);
	}
	/**
	* End panning
	* Must call if `panStart()` was called
	*/
	panEnd() {
		return this._getUpdatedState({ startPanLngLat: null });
	}
	/**
	* Start rotating
	* @param {[Number, Number]} pos - position on screen where the center is
	*/
	rotateStart({ pos }) {
		const altitude = this.getAltitude?.(pos);
		return this._getUpdatedState({
			startRotatePos: pos,
			startRotateLngLat: altitude !== void 0 ? this._unproject3D(pos, altitude) : void 0,
			startBearing: this.getViewportProps().bearing,
			startPitch: this.getViewportProps().pitch
		});
	}
	/**
	* Rotate
	* @param {[Number, Number]} pos - position on screen where the center is
	*/
	rotate({ pos, deltaAngleX = 0, deltaAngleY = 0 }) {
		const { startRotatePos, startRotateLngLat, startBearing, startPitch } = this.getState();
		if (!startRotatePos || startBearing === void 0 || startPitch === void 0) return this;
		let newRotation;
		if (pos) newRotation = this._getNewRotation(pos, startRotatePos, startPitch, startBearing);
		else newRotation = {
			bearing: startBearing + deltaAngleX,
			pitch: startPitch + deltaAngleY
		};
		if (startRotateLngLat) {
			const rotatedViewport = this.makeViewport({
				...this.getViewportProps(),
				...newRotation
			});
			const panMethod = "panByPosition3D" in rotatedViewport ? "panByPosition3D" : "panByPosition";
			return this._getUpdatedState({
				...newRotation,
				...rotatedViewport[panMethod](startRotateLngLat, startRotatePos)
			});
		}
		return this._getUpdatedState(newRotation);
	}
	/**
	* End rotating
	* Must call if `rotateStart()` was called
	*/
	rotateEnd() {
		return this._getUpdatedState({
			startRotatePos: null,
			startRotateLngLat: null,
			startBearing: null,
			startPitch: null
		});
	}
	/**
	* Start zooming
	* @param {[Number, Number]} pos - position on screen where the center is
	*/
	zoomStart({ pos }) {
		return this._getUpdatedState({
			startZoomLngLat: this._unproject(pos),
			startZoom: this.getViewportProps().zoom
		});
	}
	/**
	* Zoom
	* @param {[Number, Number]} pos - position on screen where the current center is
	* @param {[Number, Number]} startPos - the center position at
	*   the start of the operation. Must be supplied of `zoomStart()` was not called
	* @param {Number} scale - a number between [0, 1] specifying the accumulated
	*   relative scale.
	*/
	zoom({ pos, startPos, scale }) {
		let { startZoom, startZoomLngLat } = this.getState();
		if (!startZoomLngLat) {
			startZoom = this.getViewportProps().zoom;
			startZoomLngLat = this._unproject(startPos) || this._unproject(pos);
		}
		if (!startZoomLngLat) return this;
		const zoom = this._constrainZoom(startZoom + Math.log2(scale));
		const zoomedViewport = this.makeViewport({
			...this.getViewportProps(),
			zoom
		});
		return this._getUpdatedState({
			zoom,
			...zoomedViewport.panByPosition(startZoomLngLat, pos)
		});
	}
	/**
	* End zooming
	* Must call if `zoomStart()` was called
	*/
	zoomEnd() {
		return this._getUpdatedState({
			startZoomLngLat: null,
			startZoom: null
		});
	}
	zoomIn(speed = 2) {
		return this._zoomFromCenter(speed);
	}
	zoomOut(speed = 2) {
		return this._zoomFromCenter(1 / speed);
	}
	moveLeft(speed = 100) {
		return this._panFromCenter([speed, 0]);
	}
	moveRight(speed = 100) {
		return this._panFromCenter([-speed, 0]);
	}
	moveUp(speed = 100) {
		return this._panFromCenter([0, speed]);
	}
	moveDown(speed = 100) {
		return this._panFromCenter([0, -speed]);
	}
	rotateLeft(speed = 15) {
		return this._getUpdatedState({ bearing: this.getViewportProps().bearing - speed });
	}
	rotateRight(speed = 15) {
		return this._getUpdatedState({ bearing: this.getViewportProps().bearing + speed });
	}
	rotateUp(speed = 10) {
		return this._getUpdatedState({ pitch: this.getViewportProps().pitch + speed });
	}
	rotateDown(speed = 10) {
		return this._getUpdatedState({ pitch: this.getViewportProps().pitch - speed });
	}
	shortestPathFrom(viewState) {
		const fromProps = viewState.getViewportProps();
		const props = { ...this.getViewportProps() };
		const { bearing, longitude } = props;
		if (Math.abs(bearing - fromProps.bearing) > 180) props.bearing = bearing < 0 ? bearing + 360 : bearing - 360;
		if (Math.abs(longitude - fromProps.longitude) > 180) props.longitude = longitude < 0 ? longitude + 360 : longitude - 360;
		return props;
	}
	applyConstraints(props) {
		const { maxPitch, minPitch, pitch, longitude, bearing, normalize, maxBounds } = props;
		if (normalize) {
			if (longitude < -180 || longitude > 180) props.longitude = mod(longitude + 180, 360) - 180;
			if (bearing < -180 || bearing > 180) props.bearing = mod(bearing + 180, 360) - 180;
		}
		props.pitch = clamp(pitch, minPitch, maxPitch);
		props.zoom = this._constrainZoom(props.zoom, props);
		if (maxBounds) {
			const bl = lngLatToWorld(maxBounds[0]);
			const tr = lngLatToWorld(maxBounds[1]);
			const scale = 2 ** props.zoom;
			const halfWidth = props.width / 2 / scale;
			const halfHeight = props.height / 2 / scale;
			const [minLng, minLat] = worldToLngLat([bl[0] + halfWidth, bl[1] + halfHeight]);
			const [maxLng, maxLat] = worldToLngLat([tr[0] - halfWidth, tr[1] - halfHeight]);
			props.longitude = clamp(props.longitude, minLng, maxLng);
			props.latitude = clamp(props.latitude, minLat, maxLat);
		}
		return props;
	}
	_constrainZoom(zoom, props) {
		props || (props = this.getViewportProps());
		const { maxZoom, maxBounds } = props;
		const shouldApplyMaxBounds = maxBounds !== null && props.width > 0 && props.height > 0;
		let { minZoom } = props;
		if (shouldApplyMaxBounds) {
			const bl = lngLatToWorld(maxBounds[0]);
			const tr = lngLatToWorld(maxBounds[1]);
			const w = tr[0] - bl[0];
			const h = tr[1] - bl[1];
			if (Number.isFinite(w) && w > 0) minZoom = Math.max(minZoom, Math.log2(props.width / w));
			if (Number.isFinite(h) && h > 0) minZoom = Math.max(minZoom, Math.log2(props.height / h));
			if (minZoom > maxZoom) minZoom = maxZoom;
		}
		return clamp(zoom, minZoom, maxZoom);
	}
	_zoomFromCenter(scale) {
		const { width, height } = this.getViewportProps();
		return this.zoom({
			pos: [width / 2, height / 2],
			scale
		});
	}
	_panFromCenter(offset) {
		const { width, height } = this.getViewportProps();
		return this.pan({
			startPos: [width / 2, height / 2],
			pos: [width / 2 + offset[0], height / 2 + offset[1]]
		});
	}
	_getUpdatedState(newProps) {
		return new this.constructor({
			makeViewport: this.makeViewport,
			...this.getViewportProps(),
			...this.getState(),
			...newProps
		});
	}
	_unproject(pos) {
		const viewport = this.makeViewport(this.getViewportProps());
		return pos && viewport.unproject(pos);
	}
	_unproject3D(pos, altitude) {
		return this.makeViewport(this.getViewportProps()).unproject(pos, { targetZ: altitude });
	}
	_getNewRotation(pos, startPos, startPitch, startBearing) {
		const deltaX = pos[0] - startPos[0];
		const deltaY = pos[1] - startPos[1];
		const centerY = pos[1];
		const startY = startPos[1];
		const { width, height } = this.getViewportProps();
		const deltaScaleX = deltaX / width;
		let deltaScaleY = 0;
		if (deltaY > 0) {
			if (Math.abs(height - startY) > PITCH_MOUSE_THRESHOLD) deltaScaleY = deltaY / (startY - height) * PITCH_ACCEL;
		} else if (deltaY < 0) {
			if (startY > PITCH_MOUSE_THRESHOLD) deltaScaleY = 1 - centerY / startY;
		}
		deltaScaleY = clamp(deltaScaleY, -1, 1);
		const { minPitch, maxPitch } = this.getViewportProps();
		const bearing = startBearing + 180 * deltaScaleX;
		let pitch = startPitch;
		if (deltaScaleY > 0) pitch = startPitch + deltaScaleY * (maxPitch - startPitch);
		else if (deltaScaleY < 0) pitch = startPitch - deltaScaleY * (minPitch - startPitch);
		return {
			pitch,
			bearing
		};
	}
};
var MapController = class extends Controller {
	constructor() {
		super(...arguments);
		this.ControllerState = MapState;
		this.transition = {
			transitionDuration: 300,
			transitionInterpolator: new LinearInterpolator({ transitionProps: {
				compare: [
					"longitude",
					"latitude",
					"zoom",
					"bearing",
					"pitch",
					"position"
				],
				required: [
					"longitude",
					"latitude",
					"zoom"
				]
			} })
		};
		this.dragMode = "pan";
		/**
		* Rotation pivot behavior:
		* - 'center': Rotate around viewport center (default)
		* - '2d': Rotate around pointer position at ground level (z=0)
		* - '3d': Rotate around 3D picked point (requires pickPosition callback)
		*/
		this.rotationPivot = "center";
		/** Add altitude to rotateStart params based on rotationPivot mode */
		this._getAltitude = (pos) => {
			if (this.rotationPivot === "2d") return 0;
			else if (this.rotationPivot === "3d") {
				if (this.pickPosition) {
					const { x, y } = this.props;
					const pickResult = this.pickPosition(x + pos[0], y + pos[1]);
					if (pickResult && pickResult.coordinate && pickResult.coordinate.length >= 3) return pickResult.coordinate[2];
				}
			}
		};
	}
	setProps(props) {
		if ("rotationPivot" in props) this.rotationPivot = props.rotationPivot || "center";
		props.getAltitude = this._getAltitude;
		props.position = props.position || [
			0,
			0,
			0
		];
		props.maxBounds = props.maxBounds || (props.normalize === false ? null : WEB_MERCATOR_MAX_BOUNDS);
		super.setProps(props);
	}
	updateViewport(newControllerState, extraProps = null, interactionState = {}) {
		const state = newControllerState.getState();
		if (interactionState.isDragging && state.startRotateLngLat) interactionState = {
			...interactionState,
			rotationPivotPosition: state.startRotateLngLat
		};
		else if (interactionState.isDragging === false) interactionState = {
			...interactionState,
			rotationPivotPosition: void 0
		};
		super.updateViewport(newControllerState, extraProps, interactionState);
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/views/map-view.js
var MapView = class extends View {
	constructor(props = {}) {
		super(props);
	}
	getViewportType() {
		return WebMercatorViewport;
	}
	get ControllerType() {
		return MapController;
	}
};
MapView.displayName = "MapView";
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/effect-manager.js
var DEFAULT_LIGHTING_EFFECT = new LightingEffect();
/** Sort two effects. Returns 0 if equal, negative if e1 < e2, positive if e1 > e2 */
function compareEffects(e1, e2) {
	return (e1.order ?? Infinity) - (e2.order ?? Infinity);
}
var EffectManager = class {
	constructor(context) {
		this._resolvedEffects = [];
		/** Effect instances and order preference pairs, sorted by order */
		this._defaultEffects = [];
		this.effects = [];
		this._context = context;
		this._needsRedraw = "Initial render";
		this._setEffects([]);
	}
	/**
	* Register a new default effect, i.e. an effect presents regardless of user supplied props.effects
	*/
	addDefaultEffect(effect) {
		const defaultEffects = this._defaultEffects;
		if (!defaultEffects.find((e) => e.id === effect.id)) {
			const index = defaultEffects.findIndex((e) => compareEffects(e, effect) > 0);
			if (index < 0) defaultEffects.push(effect);
			else defaultEffects.splice(index, 0, effect);
			effect.setup(this._context);
			this._setEffects(this.effects);
		}
	}
	setProps(props) {
		if ("effects" in props) {
			if (!deepEqual(props.effects, this.effects, 1)) this._setEffects(props.effects);
		}
	}
	needsRedraw(opts = { clearRedrawFlags: false }) {
		const redraw = this._needsRedraw;
		if (opts.clearRedrawFlags) this._needsRedraw = false;
		return redraw;
	}
	getEffects() {
		return this._resolvedEffects;
	}
	_setEffects(effects) {
		const oldEffectsMap = {};
		for (const effect of this.effects) oldEffectsMap[effect.id] = effect;
		const nextEffects = [];
		for (const effect of effects) {
			const oldEffect = oldEffectsMap[effect.id];
			let effectToAdd = effect;
			if (oldEffect && oldEffect !== effect) if (oldEffect.setProps) {
				oldEffect.setProps(effect.props);
				effectToAdd = oldEffect;
			} else oldEffect.cleanup(this._context);
			else if (!oldEffect) effect.setup(this._context);
			nextEffects.push(effectToAdd);
			delete oldEffectsMap[effect.id];
		}
		for (const removedEffectId in oldEffectsMap) oldEffectsMap[removedEffectId].cleanup(this._context);
		this.effects = nextEffects;
		this._resolvedEffects = nextEffects.concat(this._defaultEffects);
		if (!effects.some((effect) => effect instanceof LightingEffect)) this._resolvedEffects.push(DEFAULT_LIGHTING_EFFECT);
		this._needsRedraw = "effects changed";
	}
	finalize() {
		for (const effect of this._resolvedEffects) effect.cleanup(this._context);
		this.effects.length = 0;
		this._resolvedEffects.length = 0;
		this._defaultEffects.length = 0;
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/passes/draw-layers-pass.js
var DrawLayersPass = class extends LayersPass {
	shouldDrawLayer(layer) {
		const { operation } = layer.props;
		return operation.includes("draw") || operation.includes("terrain");
	}
	render(options) {
		return this._render(options);
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/deck-renderer.js
var TRACE_RENDER_LAYERS = "deckRenderer.renderLayers";
var DeckRenderer = class {
	constructor(device, opts = {}) {
		this.device = device;
		this.stats = opts.stats;
		this.layerFilter = null;
		this.drawPickingColors = false;
		this.drawLayersPass = new DrawLayersPass(device);
		this.pickLayersPass = new PickLayersPass(device);
		this.renderCount = 0;
		this._needsRedraw = "Initial render";
		this.renderBuffers = [];
		this.lastPostProcessEffect = null;
	}
	setProps(props) {
		if (this.layerFilter !== props.layerFilter) {
			this.layerFilter = props.layerFilter;
			this._needsRedraw = "layerFilter changed";
		}
		if (this.drawPickingColors !== props.drawPickingColors) {
			this.drawPickingColors = props.drawPickingColors;
			this._needsRedraw = "drawPickingColors changed";
		}
	}
	renderLayers(opts) {
		if (!opts.viewports.length) return;
		const layerPass = this.drawPickingColors ? this.pickLayersPass : this.drawLayersPass;
		const renderOpts = {
			layerFilter: this.layerFilter,
			isPicking: this.drawPickingColors,
			...opts
		};
		if (renderOpts.effects) this._preRender(renderOpts.effects, renderOpts);
		const outputBuffer = this.lastPostProcessEffect ? this.renderBuffers[0] : renderOpts.target;
		if (this.lastPostProcessEffect) {
			renderOpts.clearColor = [
				0,
				0,
				0,
				0
			];
			renderOpts.clearCanvas = true;
		}
		const renderResult = layerPass.render({
			...renderOpts,
			target: outputBuffer
		});
		const renderStats = "stats" in renderResult ? renderResult.stats : renderResult;
		if (renderOpts.effects) {
			if (this.lastPostProcessEffect) renderOpts.clearCanvas = opts.clearCanvas === void 0 ? true : opts.clearCanvas;
			this._postRender(renderOpts.effects, renderOpts);
		}
		this.renderCount++;
		debug(TRACE_RENDER_LAYERS, this, renderStats, opts);
		this._updateStats(renderStats);
	}
	needsRedraw(opts = { clearRedrawFlags: false }) {
		const redraw = this._needsRedraw;
		if (opts.clearRedrawFlags) this._needsRedraw = false;
		return redraw;
	}
	finalize() {
		const { renderBuffers } = this;
		for (const buffer of renderBuffers) buffer.delete();
		renderBuffers.length = 0;
	}
	_updateStats(source) {
		if (!this.stats) return;
		let layersCount = 0;
		for (const { visibleCount } of source) layersCount += visibleCount;
		this.stats.get("Layers rendered").addCount(layersCount);
	}
	_preRender(effects, opts) {
		this.lastPostProcessEffect = null;
		opts.preRenderStats = opts.preRenderStats || {};
		for (const effect of effects) {
			opts.preRenderStats[effect.id] = effect.preRender(opts);
			if (effect.postRender) this.lastPostProcessEffect = effect.id;
		}
		if (this.lastPostProcessEffect) this._resizeRenderBuffers();
	}
	_resizeRenderBuffers() {
		const { renderBuffers } = this;
		const size = this.device.canvasContext.getDrawingBufferSize();
		const [width, height] = size;
		if (renderBuffers.length === 0) [0, 1].map((i) => {
			const texture = this.device.createTexture({
				sampler: {
					minFilter: "linear",
					magFilter: "linear"
				},
				width,
				height
			});
			renderBuffers.push(this.device.createFramebuffer({
				id: `deck-renderbuffer-${i}`,
				colorAttachments: [texture]
			}));
		});
		for (const buffer of renderBuffers) buffer.resize(size);
	}
	_postRender(effects, opts) {
		const { renderBuffers } = this;
		const params = {
			...opts,
			inputBuffer: renderBuffers[0],
			swapBuffer: renderBuffers[1]
		};
		for (const effect of effects) if (effect.postRender) {
			params.target = effect.id === this.lastPostProcessEffect ? opts.target : void 0;
			const buffer = effect.postRender(params);
			params.inputBuffer = buffer;
			params.swapBuffer = buffer === renderBuffers[0] ? renderBuffers[1] : renderBuffers[0];
		}
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/picking/query-object.js
var NO_PICKED_OBJECT = {
	pickedColor: null,
	pickedObjectIndex: -1
};
/**
* Pick at a specified pixel with a tolerance radius
* Returns the closest object to the pixel in shape `{pickedColor, pickedLayer, pickedObjectIndex}`
*/
function getClosestObject({ pickedColors, decodePickingColor, deviceX, deviceY, deviceRadius, deviceRect }) {
	const { x, y, width, height } = deviceRect;
	let minSquareDistanceToCenter = deviceRadius * deviceRadius;
	let closestPixelIndex = -1;
	let i = 0;
	for (let row = 0; row < height; row++) {
		const dy = row + y - deviceY;
		const dy2 = dy * dy;
		if (dy2 > minSquareDistanceToCenter) i += 4 * width;
		else for (let col = 0; col < width; col++) {
			if (pickedColors[i + 3] - 1 >= 0) {
				const dx = col + x - deviceX;
				const d2 = dx * dx + dy2;
				if (d2 <= minSquareDistanceToCenter) {
					minSquareDistanceToCenter = d2;
					closestPixelIndex = i;
				}
			}
			i += 4;
		}
	}
	if (closestPixelIndex >= 0) {
		const pickedColor = pickedColors.slice(closestPixelIndex, closestPixelIndex + 4);
		const pickedObject = decodePickingColor(pickedColor);
		if (pickedObject) {
			const dy = Math.floor(closestPixelIndex / 4 / width);
			const dx = closestPixelIndex / 4 - dy * width;
			return {
				...pickedObject,
				pickedColor,
				pickedX: x + dx,
				pickedY: y + dy
			};
		}
		defaultLogger.error("Picked non-existent layer. Is picking buffer corrupt?")();
	}
	return NO_PICKED_OBJECT;
}
/**
* Examines a picking buffer for unique colors
* Returns array of unique objects in shape `{x, y, pickedColor, pickedLayer, pickedObjectIndex}`
*/
function getUniqueObjects({ pickedColors, decodePickingColor }) {
	const uniqueColors = /* @__PURE__ */ new Map();
	if (pickedColors) {
		for (let i = 0; i < pickedColors.length; i += 4) if (pickedColors[i + 3] - 1 >= 0) {
			const pickedColor = pickedColors.slice(i, i + 4);
			const colorKey = pickedColor.join(",");
			if (!uniqueColors.has(colorKey)) {
				const pickedObject = decodePickingColor(pickedColor);
				if (pickedObject) uniqueColors.set(colorKey, {
					...pickedObject,
					color: pickedColor
				});
				else defaultLogger.error("Picked non-existent layer. Is picking buffer corrupt?")();
			}
		}
	}
	return Array.from(uniqueColors.values());
}
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/picking/pick-info.js
/** Generates some basic information of the picking action: x, y, coordinates etc.
* Regardless if anything is picked
*/
function getEmptyPickingInfo({ pickInfo, viewports, pixelRatio, x, y, z }) {
	let pickedViewport = viewports[0];
	if (viewports.length > 1) pickedViewport = getViewportFromCoordinates(pickInfo?.pickedViewports || viewports, {
		x,
		y
	});
	let coordinate;
	if (pickedViewport) {
		const point = [x - pickedViewport.x, y - pickedViewport.y];
		if (z !== void 0) point[2] = z;
		coordinate = pickedViewport.unproject(point);
	}
	return {
		color: null,
		layer: null,
		viewport: pickedViewport,
		index: -1,
		picked: false,
		x,
		y,
		pixel: [x, y],
		coordinate,
		devicePixel: pickInfo && "pickedX" in pickInfo ? [pickInfo.pickedX, pickInfo.pickedY] : void 0,
		pixelRatio
	};
}
/** Generates the picking info of a picking operation */
function processPickInfo(opts) {
	const { pickInfo, lastPickedInfo, mode, layers } = opts;
	const { pickedColor, pickedLayer, pickedObjectIndex } = pickInfo;
	const affectedLayers = pickedLayer ? [pickedLayer] : [];
	if (mode === "hover") {
		const lastPickedPixelIndex = lastPickedInfo.index;
		const lastPickedLayerId = lastPickedInfo.layerId;
		const pickedLayerId = pickedLayer ? pickedLayer.props.id : null;
		if (pickedLayerId !== lastPickedLayerId || pickedObjectIndex !== lastPickedPixelIndex) {
			if (pickedLayerId !== lastPickedLayerId) {
				const lastPickedLayer = layers.find((layer) => layer.props.id === lastPickedLayerId);
				if (lastPickedLayer) affectedLayers.unshift(lastPickedLayer);
			}
			lastPickedInfo.layerId = pickedLayerId;
			lastPickedInfo.index = pickedObjectIndex;
			lastPickedInfo.info = null;
		}
	}
	const baseInfo = getEmptyPickingInfo(opts);
	const infos = /* @__PURE__ */ new Map();
	infos.set(null, baseInfo);
	affectedLayers.forEach((layer) => {
		let info = { ...baseInfo };
		if (layer === pickedLayer) {
			info.color = pickedColor;
			info.index = pickedObjectIndex;
			info.picked = true;
		}
		info = getLayerPickingInfo({
			layer,
			info,
			mode
		});
		const rootLayer = info.layer;
		if (layer === pickedLayer && mode === "hover") lastPickedInfo.info = info;
		infos.set(rootLayer.id, info);
		if (mode === "hover") rootLayer.updateAutoHighlight(info);
	});
	return infos;
}
/** Walk up the layer composite chain to populate the info object */
function getLayerPickingInfo({ layer, info, mode }) {
	while (layer && info) {
		const sourceLayer = info.layer || null;
		info.sourceLayer = sourceLayer;
		info.layer = layer;
		info = layer.getPickingInfo({
			info,
			mode,
			sourceLayer
		});
		layer = layer.parent;
	}
	return info;
}
/** Indentifies which viewport, if any corresponds to x and y
If multiple viewports contain the target pixel, last viewport drawn is returend
Returns first viewport if no match */
function getViewportFromCoordinates(viewports, pixel) {
	for (let i = viewports.length - 1; i >= 0; i--) {
		const viewport = viewports[i];
		if (viewport.containsPixel(pixel)) return viewport;
	}
	return viewports[0];
}
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/deck-picker.js
/** Manages picking in a Deck context */
var DeckPicker = class {
	constructor(device, opts = {}) {
		this._pickable = true;
		this.device = device;
		this.stats = opts.stats;
		this.pickLayersPass = new PickLayersPass(device);
		this.lastPickedInfo = {
			index: -1,
			layerId: null,
			info: null
		};
	}
	setProps(props) {
		if ("layerFilter" in props) this.layerFilter = props.layerFilter;
		if ("_pickable" in props) this._pickable = props._pickable;
	}
	finalize() {
		if (this.pickingFBO) this.pickingFBO.destroy();
		if (this.depthFBO) this.depthFBO.destroy();
	}
	/**
	* Pick the closest info at given coordinate
	* @returns Promise that resolves with picking info
	*/
	pickObjectAsync(opts) {
		return this._pickClosestObjectAsync(opts);
	}
	/**
	* Picks a list of unique infos within a bounding box
	* @returns Promise that resolves to all unique infos within a bounding box
	*/
	pickObjectsAsync(opts) {
		return this._pickVisibleObjectsAsync(opts);
	}
	/**
	* Pick the closest info at given coordinate
	* @returns picking info
	* @note WebGL only - use pickObjectAsync instead
	*/
	pickObject(opts) {
		return this._pickClosestObject(opts);
	}
	/**
	* Get all unique infos within a bounding box
	* @returns all unique infos within a bounding box
	* @note WebGL only - use pickObjectAsync instead
	*/
	pickObjects(opts) {
		return this._pickVisibleObjects(opts);
	}
	getLastPickedObject({ x, y, layers, viewports }, lastPickedInfo = this.lastPickedInfo.info) {
		const lastPickedLayerId = lastPickedInfo && lastPickedInfo.layer && lastPickedInfo.layer.id;
		const lastPickedViewportId = lastPickedInfo && lastPickedInfo.viewport && lastPickedInfo.viewport.id;
		const layer = lastPickedLayerId ? layers.find((l) => l.id === lastPickedLayerId) : null;
		const viewport = lastPickedViewportId && viewports.find((v) => v.id === lastPickedViewportId) || viewports[0];
		const info = {
			x,
			y,
			viewport,
			coordinate: viewport && viewport.unproject([x - viewport.x, y - viewport.y]),
			layer
		};
		return {
			...lastPickedInfo,
			...info
		};
	}
	/** Ensures that picking framebuffer exists and matches the canvas size */
	_resizeBuffer(canvasContext = this.device.getDefaultCanvasContext()) {
		if (!this.pickingFBO) {
			const pickingColorTexture = this.device.createTexture({
				format: "rgba8unorm",
				width: 1,
				height: 1,
				usage: Texture.RENDER_ATTACHMENT | Texture.COPY_SRC
			});
			this.pickingFBO = this.device.createFramebuffer({
				colorAttachments: [pickingColorTexture],
				depthStencilAttachment: "depth16unorm"
			});
			if (this.device.isTextureFormatRenderable("rgba32float")) {
				const depthColorTexture = this.device.createTexture({
					format: "rgba32float",
					width: 1,
					height: 1,
					usage: Texture.RENDER_ATTACHMENT | Texture.COPY_SRC
				});
				const depthFBO = this.device.createFramebuffer({
					colorAttachments: [depthColorTexture],
					depthStencilAttachment: "depth16unorm"
				});
				this.depthFBO = depthFBO;
			}
		}
		const [width, height] = canvasContext.getDrawingBufferSize();
		this.pickingFBO?.resize({
			width,
			height
		});
		this.depthFBO?.resize({
			width,
			height
		});
	}
	/** Preliminary filtering of the layers list. Skid picking pass if no layer is pickable. */
	_getPickable(layers) {
		if (this._pickable === false) return null;
		const pickableLayers = layers.filter((layer) => this.pickLayersPass.shouldDrawLayer(layer) && !layer.isComposite);
		return pickableLayers.length ? pickableLayers : null;
	}
	/**
	* Pick the closest object at the given coordinate
	*/
	async _pickClosestObjectAsync({ layers, views, viewports, x, y, radius = 0, depth = 1, mode = "query", unproject3D, canvasContext = this.device.getDefaultCanvasContext(), onViewportActive, effects }) {
		const pixelRatio = canvasContext.cssToDeviceRatio();
		const pickableLayers = this._getPickable(layers);
		if (!pickableLayers || viewports.length === 0) return {
			result: [],
			emptyInfo: getEmptyPickingInfo({
				viewports,
				x,
				y,
				pixelRatio
			})
		};
		this._resizeBuffer(canvasContext);
		const devicePixelRange = canvasContext.cssToDevicePixels([x, y], true);
		const devicePixel = [devicePixelRange.x + Math.floor(devicePixelRange.width / 2), devicePixelRange.y + Math.floor(devicePixelRange.height / 2)];
		const deviceRadius = Math.round(radius * pixelRatio);
		const { width, height } = this.pickingFBO;
		const deviceRect = this._getPickingRect({
			deviceX: devicePixel[0],
			deviceY: devicePixel[1],
			deviceRadius,
			deviceWidth: width,
			deviceHeight: height
		});
		const cullRect = {
			x: x - radius,
			y: y - radius,
			width: radius * 2 + 1,
			height: radius * 2 + 1
		};
		let infos;
		const result = [];
		const affectedLayers = /* @__PURE__ */ new Set();
		for (let i = 0; i < depth; i++) {
			let pickInfo;
			if (deviceRect) pickInfo = getClosestObject({
				...await this._drawAndSampleAsync({
					layers: pickableLayers,
					views,
					viewports,
					onViewportActive,
					deviceRect,
					cullRect,
					effects,
					pass: `picking:${mode}`
				}),
				deviceX: devicePixel[0],
				deviceY: devicePixel[1],
				deviceRadius,
				deviceRect
			});
			else pickInfo = {
				pickedColor: null,
				pickedObjectIndex: -1
			};
			let z;
			const depthLayers = this._getDepthLayers(pickInfo, pickableLayers, unproject3D);
			if (depthLayers.length > 0) {
				const { pickedColors: pickedColors2 } = await this._drawAndSampleAsync({
					layers: depthLayers,
					views,
					viewports,
					onViewportActive,
					deviceRect: {
						x: pickInfo.pickedX ?? devicePixel[0],
						y: pickInfo.pickedY ?? devicePixel[1],
						width: 1,
						height: 1
					},
					cullRect,
					effects,
					pass: `picking:${mode}:z`
				}, true);
				if (pickedColors2[3]) z = pickedColors2[0];
			}
			if (pickInfo.pickedLayer && i + 1 < depth) {
				affectedLayers.add(pickInfo.pickedLayer);
				pickInfo.pickedLayer.disablePickingIndex(pickInfo.pickedObjectIndex);
			}
			infos = processPickInfo({
				pickInfo,
				lastPickedInfo: this.lastPickedInfo,
				mode,
				layers: pickableLayers,
				viewports,
				x,
				y,
				z,
				pixelRatio
			});
			for (const info of infos.values()) if (info.layer) result.push(info);
			if (!pickInfo.pickedColor) break;
		}
		for (const layer of affectedLayers) layer.restorePickingColors();
		return {
			result,
			emptyInfo: infos.get(null)
		};
	}
	/**
	* Pick the closest object at the given coordinate
	* @deprecated WebGL only
	*/
	_pickClosestObject({ layers, views, viewports, x, y, radius = 0, depth = 1, mode = "query", unproject3D, canvasContext = this.device.getDefaultCanvasContext(), onViewportActive, effects }) {
		const pixelRatio = canvasContext.cssToDeviceRatio();
		const pickableLayers = this._getPickable(layers);
		if (!pickableLayers || viewports.length === 0) return {
			result: [],
			emptyInfo: getEmptyPickingInfo({
				viewports,
				x,
				y,
				pixelRatio
			})
		};
		this._resizeBuffer(canvasContext);
		const devicePixelRange = canvasContext.cssToDevicePixels([x, y], true);
		const devicePixel = [devicePixelRange.x + Math.floor(devicePixelRange.width / 2), devicePixelRange.y + Math.floor(devicePixelRange.height / 2)];
		const deviceRadius = Math.round(radius * pixelRatio);
		const { width, height } = this.pickingFBO;
		const deviceRect = this._getPickingRect({
			deviceX: devicePixel[0],
			deviceY: devicePixel[1],
			deviceRadius,
			deviceWidth: width,
			deviceHeight: height
		});
		const cullRect = {
			x: x - radius,
			y: y - radius,
			width: radius * 2 + 1,
			height: radius * 2 + 1
		};
		let infos;
		const result = [];
		const affectedLayers = /* @__PURE__ */ new Set();
		for (let i = 0; i < depth; i++) {
			let pickInfo;
			if (deviceRect) pickInfo = getClosestObject({
				...this._drawAndSample({
					layers: pickableLayers,
					views,
					viewports,
					onViewportActive,
					deviceRect,
					cullRect,
					effects,
					pass: `picking:${mode}`
				}),
				deviceX: devicePixel[0],
				deviceY: devicePixel[1],
				deviceRadius,
				deviceRect
			});
			else pickInfo = {
				pickedColor: null,
				pickedObjectIndex: -1
			};
			let z;
			const depthLayers = this._getDepthLayers(pickInfo, pickableLayers, unproject3D);
			if (depthLayers.length > 0) {
				const { pickedColors: pickedColors2 } = this._drawAndSample({
					layers: depthLayers,
					views,
					viewports,
					onViewportActive,
					deviceRect: {
						x: pickInfo.pickedX ?? devicePixel[0],
						y: pickInfo.pickedY ?? devicePixel[1],
						width: 1,
						height: 1
					},
					cullRect,
					effects,
					pass: `picking:${mode}:z`
				}, true);
				if (pickedColors2[3]) z = pickedColors2[0];
			}
			if (pickInfo.pickedLayer && i + 1 < depth) {
				affectedLayers.add(pickInfo.pickedLayer);
				pickInfo.pickedLayer.disablePickingIndex(pickInfo.pickedObjectIndex);
			}
			infos = processPickInfo({
				pickInfo,
				lastPickedInfo: this.lastPickedInfo,
				mode,
				layers: pickableLayers,
				viewports,
				x,
				y,
				z,
				pixelRatio
			});
			for (const info of infos.values()) if (info.layer) result.push(info);
			if (!pickInfo.pickedColor) break;
		}
		for (const layer of affectedLayers) layer.restorePickingColors();
		return {
			result,
			emptyInfo: infos.get(null)
		};
	}
	/**
	* Pick all objects within the given bounding box
	*/
	async _pickVisibleObjectsAsync({ layers, views, viewports, x, y, width = 1, height = 1, mode = "query", maxObjects = null, canvasContext = this.device.getDefaultCanvasContext(), onViewportActive, effects }) {
		const pickableLayers = this._getPickable(layers);
		if (!pickableLayers || viewports.length === 0) return [];
		this._resizeBuffer(canvasContext);
		const pixelRatio = canvasContext.cssToDeviceRatio();
		const leftTop = canvasContext.cssToDevicePixels([x, y], true);
		const deviceLeft = leftTop.x;
		const deviceTop = leftTop.y + leftTop.height;
		const rightBottom = canvasContext.cssToDevicePixels([x + width, y + height], true);
		const deviceRight = rightBottom.x + rightBottom.width;
		const deviceBottom = rightBottom.y;
		const deviceRect = {
			x: deviceLeft,
			y: deviceBottom,
			width: deviceRight - deviceLeft,
			height: deviceTop - deviceBottom
		};
		const pickInfos = getUniqueObjects(await this._drawAndSampleAsync({
			layers: pickableLayers,
			views,
			viewports,
			onViewportActive,
			deviceRect,
			cullRect: {
				x,
				y,
				width,
				height
			},
			effects,
			pass: `picking:${mode}`
		}));
		const uniquePickedObjects = /* @__PURE__ */ new Map();
		const uniqueInfos = [];
		const limitMaxObjects = Number.isFinite(maxObjects);
		for (let i = 0; i < pickInfos.length; i++) {
			if (limitMaxObjects && uniqueInfos.length >= maxObjects) break;
			const pickInfo = pickInfos[i];
			let info = {
				color: pickInfo.pickedColor,
				layer: null,
				index: pickInfo.pickedObjectIndex,
				picked: true,
				x,
				y,
				pixelRatio
			};
			info = getLayerPickingInfo({
				layer: pickInfo.pickedLayer,
				info,
				mode
			});
			const pickedLayerId = info.layer.id;
			if (!uniquePickedObjects.has(pickedLayerId)) uniquePickedObjects.set(pickedLayerId, /* @__PURE__ */ new Set());
			const uniqueObjectsInLayer = uniquePickedObjects.get(pickedLayerId);
			const pickedObjectKey = info.object ?? info.index;
			if (!uniqueObjectsInLayer.has(pickedObjectKey)) {
				uniqueObjectsInLayer.add(pickedObjectKey);
				uniqueInfos.push(info);
			}
		}
		return uniqueInfos;
	}
	/**
	* Pick all objects within the given bounding box
	* @deprecated WebGL only
	*/
	_pickVisibleObjects({ layers, views, viewports, x, y, width = 1, height = 1, mode = "query", maxObjects = null, canvasContext = this.device.getDefaultCanvasContext(), onViewportActive, effects }) {
		const pickableLayers = this._getPickable(layers);
		if (!pickableLayers || viewports.length === 0) return [];
		this._resizeBuffer(canvasContext);
		const pixelRatio = canvasContext.cssToDeviceRatio();
		const leftTop = canvasContext.cssToDevicePixels([x, y], true);
		const deviceLeft = leftTop.x;
		const deviceTop = leftTop.y + leftTop.height;
		const rightBottom = canvasContext.cssToDevicePixels([x + width, y + height], true);
		const deviceRight = rightBottom.x + rightBottom.width;
		const deviceBottom = rightBottom.y;
		const deviceRect = {
			x: deviceLeft,
			y: deviceBottom,
			width: deviceRight - deviceLeft,
			height: deviceTop - deviceBottom
		};
		const pickInfos = getUniqueObjects(this._drawAndSample({
			layers: pickableLayers,
			views,
			viewports,
			onViewportActive,
			deviceRect,
			cullRect: {
				x,
				y,
				width,
				height
			},
			effects,
			pass: `picking:${mode}`
		}));
		const uniquePickedObjects = /* @__PURE__ */ new Map();
		const uniqueInfos = [];
		const limitMaxObjects = Number.isFinite(maxObjects);
		for (let i = 0; i < pickInfos.length; i++) {
			if (limitMaxObjects && uniqueInfos.length >= maxObjects) break;
			const pickInfo = pickInfos[i];
			let info = {
				color: pickInfo.pickedColor,
				layer: null,
				index: pickInfo.pickedObjectIndex,
				picked: true,
				x,
				y,
				pixelRatio
			};
			info = getLayerPickingInfo({
				layer: pickInfo.pickedLayer,
				info,
				mode
			});
			const pickedLayerId = info.layer.id;
			if (!uniquePickedObjects.has(pickedLayerId)) uniquePickedObjects.set(pickedLayerId, /* @__PURE__ */ new Set());
			const uniqueObjectsInLayer = uniquePickedObjects.get(pickedLayerId);
			const pickedObjectKey = info.object ?? info.index;
			if (!uniqueObjectsInLayer.has(pickedObjectKey)) {
				uniqueObjectsInLayer.add(pickedObjectKey);
				uniqueInfos.push(info);
			}
		}
		return uniqueInfos;
	}
	async _drawAndSampleAsync({ layers, views, viewports, onViewportActive, deviceRect, cullRect, effects, pass }, pickZ = false) {
		const pickingFBO = pickZ ? this.depthFBO : this.pickingFBO;
		const opts = {
			layers,
			layerFilter: this.layerFilter,
			views,
			viewports,
			onViewportActive,
			pickingFBO,
			deviceRect,
			cullRect,
			effects,
			pass,
			pickZ,
			preRenderStats: {},
			isPicking: true
		};
		for (const effect of effects) if (effect.useInPicking) opts.preRenderStats[effect.id] = effect.preRender(opts);
		const { decodePickingColor, stats } = this.pickLayersPass.render(opts);
		this._updateStats(stats);
		const { x, y, width, height } = deviceRect;
		const texture = pickingFBO.colorAttachments[0]?.texture;
		if (!texture) throw new Error("Picking framebuffer color attachment is missing");
		const pickedColors = await this._readTextureDataAsync(texture, {
			x,
			y,
			width,
			height
		}, pickZ ? Float32Array : Uint8Array);
		if (!pickZ) {
			let hasNonZeroAlpha = false;
			for (let i = 3; i < pickedColors.length; i += 4) if (pickedColors[i] !== 0) {
				hasNonZeroAlpha = true;
				break;
			}
			if (!hasNonZeroAlpha && pickedColors.length > 0) defaultLogger.warn("Async pick readback returned only zero alpha values", {
				deviceRect,
				bytes: Array.from(pickedColors.subarray(0, Math.min(pickedColors.length, 16)))
			})();
		}
		return {
			pickedColors,
			decodePickingColor
		};
	}
	async _readTextureDataAsync(texture, options, ArrayType) {
		const { width, height } = options;
		const layout = texture.computeMemoryLayout(options);
		const readBuffer = this.device.createBuffer({
			byteLength: layout.byteLength,
			usage: Buffer.COPY_DST | Buffer.MAP_READ
		});
		try {
			texture.readBuffer(options, readBuffer);
			const readData = await readBuffer.readAsync(0, layout.byteLength);
			const bytesPerElement = ArrayType.BYTES_PER_ELEMENT;
			if (layout.bytesPerRow % bytesPerElement !== 0) throw new Error(`Texture readback row stride ${layout.bytesPerRow} is not aligned to ${bytesPerElement}-byte elements.`);
			const source = new ArrayType(readData.buffer, readData.byteOffset, layout.byteLength / bytesPerElement);
			const packedRowLength = width * 4;
			const sourceRowLength = layout.bytesPerRow / bytesPerElement;
			if (sourceRowLength < packedRowLength) throw new Error(`Texture readback row stride ${sourceRowLength} is smaller than packed row length ${packedRowLength}.`);
			const packed = new ArrayType(width * height * 4);
			for (let row = 0; row < height; row++) {
				const sourceStart = row * sourceRowLength;
				packed.set(source.subarray(sourceStart, sourceStart + packedRowLength), row * packedRowLength);
			}
			return packed;
		} finally {
			readBuffer.destroy();
		}
	}
	_drawAndSample({ layers, views, viewports, onViewportActive, deviceRect, cullRect, effects, pass }, pickZ = false) {
		const pickingFBO = pickZ ? this.depthFBO : this.pickingFBO;
		const opts = {
			layers,
			layerFilter: this.layerFilter,
			views,
			viewports,
			onViewportActive,
			pickingFBO,
			deviceRect,
			cullRect,
			effects,
			pass,
			pickZ,
			preRenderStats: {},
			isPicking: true
		};
		for (const effect of effects) if (effect.useInPicking) opts.preRenderStats[effect.id] = effect.preRender(opts);
		const { decodePickingColor, stats } = this.pickLayersPass.render(opts);
		this._updateStats(stats);
		const { x, y, width, height } = deviceRect;
		const pickedColors = new (pickZ ? Float32Array : Uint8Array)(width * height * 4);
		this.device.readPixelsToArrayWebGL(pickingFBO, {
			sourceX: x,
			sourceY: y,
			sourceWidth: width,
			sourceHeight: height,
			target: pickedColors
		});
		return {
			pickedColors,
			decodePickingColor
		};
	}
	_updateStats(source) {
		if (!this.stats) return;
		let layersCount = 0;
		for (const { visibleCount } of source) layersCount += visibleCount;
		this.stats.get("Layers picked").addCount(layersCount);
	}
	/**
	* Determine which layers to use for the depth (pickZ) pass.
	* - If a non-draped layer was picked, use just that layer.
	* - If a draped layer was picked (geometry is at z=0) or no layer was picked
	*   (e.g. no-FBO tiles at extreme zoom), fall back to terrain layers.
	*/
	_getDepthLayers(pickInfo, pickableLayers, unproject3D) {
		if (!unproject3D || !this.depthFBO) return [];
		const { pickedLayer } = pickInfo;
		const isDraped = pickedLayer?.state?.terrainDrawMode === "drape";
		if (pickedLayer && !isDraped) return [pickedLayer];
		return pickableLayers.filter((l) => l.props.operation.includes("terrain"));
	}
	/**
	* Calculate a picking rect centered on deviceX and deviceY and clipped to device
	* @returns null if pixel is outside of device
	*/
	_getPickingRect({ deviceX, deviceY, deviceRadius, deviceWidth, deviceHeight }) {
		const x = Math.max(0, deviceX - deviceRadius);
		const y = Math.max(0, deviceY - deviceRadius);
		const width = Math.min(deviceWidth, deviceX + deviceRadius + 1) - x;
		const height = Math.min(deviceHeight, deviceY + deviceRadius + 1) - y;
		if (width <= 0 || height <= 0) return null;
		return {
			x,
			y,
			width,
			height
		};
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/widget-manager.js
var PLACEMENTS = {
	"top-left": {
		top: 0,
		left: 0
	},
	"top-right": {
		top: 0,
		right: 0
	},
	"bottom-left": {
		bottom: 0,
		left: 0
	},
	"bottom-right": {
		bottom: 0,
		right: 0
	},
	fill: {
		top: 0,
		left: 0,
		bottom: 0,
		right: 0
	}
};
var DEFAULT_PLACEMENT = "top-left";
var ROOT_CONTAINER_ID = "root";
var WidgetManager = class {
	constructor({ deck, parentElement }) {
		/** Widgets added via the imperative API */
		this.defaultWidgets = [];
		/** Widgets received from the declarative API */
		this.widgets = [];
		/** Resolved widgets from both imperative and declarative APIs */
		this.resolvedWidgets = [];
		/** Mounted HTML containers */
		this.containers = {};
		/** Viewport provided to widget on redraw */
		this.lastViewports = {};
		this.deck = deck;
		parentElement?.classList.add("deck-widget-container");
		this.parentElement = parentElement;
	}
	getWidgets() {
		return this.resolvedWidgets;
	}
	/** Declarative API to configure widgets */
	setProps(props) {
		if (props.widgets && !deepEqual(props.widgets, this.widgets, 1)) {
			const nextWidgets = props.widgets.filter(Boolean);
			this._setWidgets(nextWidgets);
		}
	}
	finalize() {
		for (const widget of this.getWidgets()) this._removeWidget(widget);
		this.defaultWidgets.length = 0;
		this.resolvedWidgets.length = 0;
		for (const id in this.containers) this.containers[id].remove();
	}
	/** Imperative API. Widgets added this way are not affected by the declarative prop. */
	addDefault(widget) {
		if (!this.defaultWidgets.find((w) => w.id === widget.id)) {
			this._addWidget(widget);
			this.defaultWidgets.push(widget);
			this._setWidgets(this.widgets);
		}
	}
	onRedraw({ viewports, layers }) {
		const viewportsById = viewports.reduce((acc, v) => {
			acc[v.id] = v;
			return acc;
		}, {});
		for (const widget of this.getWidgets()) {
			const { viewId } = widget;
			if (viewId) {
				const viewport = viewportsById[viewId];
				if (viewport) {
					if (widget.onViewportChange) widget.onViewportChange(viewport);
					widget.onRedraw?.({
						viewports: [viewport],
						layers
					});
				}
			} else {
				if (widget.onViewportChange) for (const viewport of viewports) widget.onViewportChange(viewport);
				widget.onRedraw?.({
					viewports,
					layers
				});
			}
		}
		this.lastViewports = viewportsById;
		this._updateContainers();
	}
	onHover(info, event) {
		for (const widget of this.getWidgets()) {
			const { viewId } = widget;
			if (!viewId || viewId === info.viewport?.id) widget.onHover?.(info, event);
		}
	}
	onEvent(info, event) {
		const eventHandlerProp = EVENT_HANDLERS[event.type];
		if (!eventHandlerProp) return;
		for (const widget of this.getWidgets()) {
			const { viewId } = widget;
			if (!viewId || viewId === info.viewport?.id) widget[eventHandlerProp]?.(info, event);
		}
	}
	/**
	* Resolve widgets from the declarative prop
	* Initialize new widgets and remove old ones
	* Update props of existing widgets
	*/
	_setWidgets(nextWidgets) {
		const oldWidgetMap = {};
		for (const widget of this.resolvedWidgets) oldWidgetMap[widget.id] = widget;
		this.resolvedWidgets.length = 0;
		for (const widget of this.defaultWidgets) {
			oldWidgetMap[widget.id] = null;
			this.resolvedWidgets.push(widget);
		}
		for (let widget of nextWidgets) {
			const oldWidget = oldWidgetMap[widget.id];
			if (!oldWidget) this._addWidget(widget);
			else if (oldWidget.viewId !== widget.viewId || oldWidget.placement !== widget.placement) {
				this._removeWidget(oldWidget);
				this._addWidget(widget);
			} else if (widget !== oldWidget) {
				oldWidget.setProps(widget.props);
				widget = oldWidget;
			}
			oldWidgetMap[widget.id] = null;
			this.resolvedWidgets.push(widget);
		}
		for (const id in oldWidgetMap) {
			const oldWidget = oldWidgetMap[id];
			if (oldWidget) this._removeWidget(oldWidget);
		}
		this.widgets = nextWidgets;
	}
	/** Initialize new widget */
	_addWidget(widget) {
		const { viewId = null, placement = DEFAULT_PLACEMENT } = widget;
		const container = widget.props._container ?? viewId;
		widget.widgetManager = this;
		widget.deck = this.deck;
		widget.rootElement = widget._onAdd({
			deck: this.deck,
			viewId
		});
		if (widget.rootElement) this._getContainer(container, placement).append(widget.rootElement);
		widget.updateHTML();
	}
	/** Destroy an old widget */
	_removeWidget(widget) {
		widget.onRemove?.();
		if (widget.rootElement) widget.rootElement.remove();
		widget.rootElement = void 0;
		widget.deck = void 0;
		widget.widgetManager = void 0;
	}
	/** Get a container element based on view and placement */
	_getContainer(viewIdOrContainer, placement) {
		if (viewIdOrContainer && typeof viewIdOrContainer !== "string") return viewIdOrContainer;
		const containerId = viewIdOrContainer || ROOT_CONTAINER_ID;
		let viewContainer = this.containers[containerId];
		if (!viewContainer) {
			viewContainer = document.createElement("div");
			viewContainer.style.pointerEvents = "none";
			viewContainer.style.position = "absolute";
			viewContainer.style.overflow = "hidden";
			this.parentElement?.append(viewContainer);
			this.containers[containerId] = viewContainer;
		}
		let container = viewContainer.querySelector(`.${placement}`);
		if (!container) {
			container = globalThis.document.createElement("div");
			container.className = placement;
			container.style.position = "absolute";
			container.style.zIndex = "2";
			Object.assign(container.style, PLACEMENTS[placement]);
			viewContainer.append(container);
		}
		return container;
	}
	_updateContainers() {
		const canvasWidth = this.deck.width;
		const canvasHeight = this.deck.height;
		for (const id in this.containers) {
			const viewport = this.lastViewports[id] || null;
			const visible = id === ROOT_CONTAINER_ID || viewport;
			const container = this.containers[id];
			if (visible) {
				container.style.display = "block";
				container.style.left = `${viewport ? viewport.x : 0}px`;
				container.style.top = `${viewport ? viewport.y : 0}px`;
				container.style.width = `${viewport ? viewport.width : canvasWidth}px`;
				container.style.height = `${viewport ? viewport.height : canvasHeight}px`;
			} else container.style.display = "none";
		}
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/utils/apply-styles.js
function applyStyles(element, style) {
	if (style) Object.entries(style).map(([key, value]) => {
		if (key.startsWith("--")) element.style.setProperty(key, value);
		else element.style[key] = value;
	});
}
function removeStyles(element, style) {
	if (style) Object.keys(style).map((key) => {
		if (key.startsWith("--")) element.style.removeProperty(key);
		else element.style[key] = "";
	});
}
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/widget.js
var Widget = class {
	constructor(props) {
		/**
		* The view id that this widget controls. Default `null`.
		* If assigned, this widget will only respond to events occurred inside the specific view that matches this id.
		*/
		this.viewId = null;
		this.props = {
			...this.constructor.defaultProps,
			...props
		};
		this.id = this.props.id;
	}
	/** Called to update widget options */
	setProps(props) {
		const oldProps = this.props;
		const el = this.rootElement;
		if (el && oldProps.className !== props.className) {
			if (oldProps.className) el.classList.remove(oldProps.className);
			if (props.className) el.classList.add(props.className);
		}
		if (el && !deepEqual(oldProps.style, props.style, 1)) {
			removeStyles(el, oldProps.style);
			applyStyles(el, props.style);
		}
		Object.assign(this.props, props);
		this.updateHTML();
	}
	/** Update the HTML to reflect latest props and state */
	updateHTML() {
		if (this.rootElement) this.onRenderHTML(this.rootElement);
	}
	get viewIds() {
		return this.viewId ? [this.viewId] : this.deck?.getViews().map((v) => v.id) ?? [];
	}
	/** Returns the current view state for the given view */
	getViewState(viewId) {
		return this.deck?.viewManager?.getViewState(viewId) || {};
	}
	/** Updates the view state for the given view */
	setViewState(viewId, viewState) {
		this.deck?._onViewStateChange({
			viewId,
			viewState,
			interactionState: {}
		});
	}
	/**
	* Common utility to create the root DOM element for this widget
	* Configures the top-level styles and adds basic class names for theming
	* @returns an UI element that should be appended to the Deck container
	*/
	onCreateRootElement() {
		const CLASS_NAMES = [
			"deck-widget",
			this.className,
			this.props.className
		];
		const element = document.createElement("div");
		CLASS_NAMES.filter((cls) => typeof cls === "string" && cls.length > 0).forEach((className) => element.classList.add(className));
		applyStyles(element, this.props.style);
		return element;
	}
	/** Internal API called by Deck when the widget is first added to a Deck instance */
	_onAdd(params) {
		return this.onAdd(params) ?? this.onCreateRootElement();
	}
	/** Overridable by subclass - called when the widget is first added to a Deck instance
	* @returns an optional UI element that should be appended to the Deck container
	*/
	onAdd(params) {}
	/** Called when the widget is removed */
	onRemove() {}
	/** Called when the containing view is changed */
	onViewportChange(viewport) {}
	/** Called when the containing view is redrawn */
	onRedraw(params) {}
	/** Called when a hover event occurs */
	onHover(info, event) {}
	/** Called when a click event occurs */
	onClick(info, event) {}
	/** Called when a drag event occurs */
	onDrag(info, event) {}
	/** Called when a dragstart event occurs */
	onDragStart(info, event) {}
	/** Called when a dragend event occurs */
	onDragEnd(info, event) {}
};
Widget.defaultProps = {
	id: "widget",
	style: {},
	_container: null,
	className: ""
};
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/tooltip-widget.js
var defaultStyle = {
	zIndex: "1",
	position: "absolute",
	pointerEvents: "none",
	color: "#a0a7b4",
	backgroundColor: "#29323c",
	padding: "10px",
	top: "0",
	left: "0",
	display: "none"
};
var TooltipWidget = class extends Widget {
	constructor(props = {}) {
		super(props);
		this.id = "default-tooltip";
		this.placement = "fill";
		this.className = "deck-tooltip";
		this.isVisible = false;
		this.setProps(props);
	}
	onCreateRootElement() {
		const el = document.createElement("div");
		el.className = this.className;
		Object.assign(el.style, defaultStyle);
		return el;
	}
	onRenderHTML(rootElement) {}
	onViewportChange(viewport) {
		if (this.isVisible && viewport.id === this.lastViewport?.id && !viewport.equals(this.lastViewport)) this.setTooltip(null);
		this.lastViewport = viewport;
	}
	onHover(info) {
		const { deck } = this;
		const getTooltip = deck && deck.props.getTooltip;
		if (!getTooltip) return;
		const displayInfo = getTooltip(info);
		this.setTooltip(displayInfo, info.x, info.y);
	}
	setTooltip(displayInfo, x, y) {
		const el = this.rootElement;
		if (!el) return;
		if (typeof displayInfo === "string") el.innerText = displayInfo;
		else if (!displayInfo) {
			this.isVisible = false;
			el.style.display = "none";
			return;
		} else {
			if (displayInfo.text) el.innerText = displayInfo.text;
			if (displayInfo.html) el.innerHTML = displayInfo.html;
			if (displayInfo.className) el.className = displayInfo.className;
		}
		this.isVisible = true;
		el.style.display = "block";
		el.style.transform = `translate(${x}px, ${y}px)`;
		if (displayInfo && typeof displayInfo === "object" && "style" in displayInfo) Object.assign(el.style, displayInfo.style);
	}
};
TooltipWidget.defaultProps = { ...Widget.defaultProps };
//#endregion
//#region node_modules/@luma.gl/webgl/dist/context/polyfills/polyfill-webgl1-extensions.js
var WEBGL1_STATIC_EXTENSIONS = {
	WEBGL_depth_texture: { UNSIGNED_INT_24_8_WEBGL: 34042 },
	OES_element_index_uint: {},
	OES_texture_float: {},
	OES_texture_half_float: { HALF_FLOAT_OES: 5131 },
	EXT_color_buffer_float: {},
	OES_standard_derivatives: { FRAGMENT_SHADER_DERIVATIVE_HINT_OES: 35723 },
	EXT_frag_depth: {},
	EXT_blend_minmax: {
		MIN_EXT: 32775,
		MAX_EXT: 32776
	},
	EXT_shader_texture_lod: {}
};
var getWEBGL_draw_buffers = (gl) => ({
	drawBuffersWEBGL(buffers) {
		return gl.drawBuffers(buffers);
	},
	COLOR_ATTACHMENT0_WEBGL: 36064,
	COLOR_ATTACHMENT1_WEBGL: 36065,
	COLOR_ATTACHMENT2_WEBGL: 36066,
	COLOR_ATTACHMENT3_WEBGL: 36067
});
var getOES_vertex_array_object = (gl) => ({
	VERTEX_ARRAY_BINDING_OES: 34229,
	createVertexArrayOES() {
		return gl.createVertexArray();
	},
	deleteVertexArrayOES(vertexArray) {
		return gl.deleteVertexArray(vertexArray);
	},
	isVertexArrayOES(vertexArray) {
		return gl.isVertexArray(vertexArray);
	},
	bindVertexArrayOES(vertexArray) {
		return gl.bindVertexArray(vertexArray);
	}
});
var getANGLE_instanced_arrays = (gl) => ({
	VERTEX_ATTRIB_ARRAY_DIVISOR_ANGLE: 35070,
	drawArraysInstancedANGLE(...args) {
		return gl.drawArraysInstanced(...args);
	},
	drawElementsInstancedANGLE(...args) {
		return gl.drawElementsInstanced(...args);
	},
	vertexAttribDivisorANGLE(...args) {
		return gl.vertexAttribDivisor(...args);
	}
});
/**
* Make browser return WebGL2 contexts even if WebGL1 contexts are requested
* @param enforce
* @returns
*/
function enforceWebGL2(enforce = true) {
	const prototype = HTMLCanvasElement.prototype;
	if (!enforce && prototype.originalGetContext) {
		prototype.getContext = prototype.originalGetContext;
		prototype.originalGetContext = void 0;
		return;
	}
	prototype.originalGetContext = prototype.getContext;
	prototype.getContext = function(contextId, options) {
		if (contextId === "webgl" || contextId === "experimental-webgl") {
			const context = this.originalGetContext("webgl2", options);
			if (context instanceof HTMLElement) polyfillWebGL1Extensions(context);
			return context;
		}
		return this.originalGetContext(contextId, options);
	};
}
/** Install WebGL1-only extensions on WebGL2 contexts */
function polyfillWebGL1Extensions(gl) {
	gl.getExtension("EXT_color_buffer_float");
	const boundExtensions = {
		...WEBGL1_STATIC_EXTENSIONS,
		WEBGL_disjoint_timer_query: gl.getExtension("EXT_disjoint_timer_query_webgl2"),
		WEBGL_draw_buffers: getWEBGL_draw_buffers(gl),
		OES_vertex_array_object: getOES_vertex_array_object(gl),
		ANGLE_instanced_arrays: getANGLE_instanced_arrays(gl)
	};
	const originalGetExtension = gl.getExtension;
	gl.getExtension = function(extensionName) {
		const ext = originalGetExtension.call(gl, extensionName);
		if (ext) return ext;
		if (extensionName in boundExtensions) return boundExtensions[extensionName];
		return null;
	};
	const originalGetSupportedExtensions = gl.getSupportedExtensions;
	gl.getSupportedExtensions = function() {
		return (originalGetSupportedExtensions.apply(gl) || [])?.concat(Object.keys(boundExtensions));
	};
}
//#endregion
//#region node_modules/@luma.gl/webgl/dist/adapter/webgl-adapter.js
var LOG_LEVEL = 1;
var WebGLAdapter = class extends Adapter {
	/** type of device's created by this adapter */
	type = "webgl";
	constructor() {
		super();
		Device.defaultProps = {
			...Device.defaultProps,
			...DEFAULT_SPECTOR_PROPS
		};
	}
	/** Force any created WebGL contexts to be WebGL2 contexts, polyfilled with WebGL1 extensions */
	enforceWebGL2(enable) {
		enforceWebGL2(enable);
	}
	/** Check if WebGL 2 is available */
	isSupported() {
		return typeof WebGL2RenderingContext !== "undefined";
	}
	isDeviceHandle(handle) {
		if (typeof WebGL2RenderingContext !== "undefined" && handle instanceof WebGL2RenderingContext) return true;
		if (typeof WebGLRenderingContext !== "undefined" && handle instanceof WebGLRenderingContext) log.warn("WebGL1 is not supported", handle)();
		return false;
	}
	/**
	* Get a device instance from a GL context
	* Creates a WebGLCanvasContext against the contexts canvas
	* @note autoResize will be disabled, assuming that whoever created the external context will be handling resizes.
	* @param gl
	* @returns
	*/
	async attach(gl, props = {}) {
		const { WebGLDevice } = await import("./webgl-device-DmZ5B3dw.js").then((n) => n.n);
		if (gl instanceof WebGLDevice) return gl;
		const existingDevice = WebGLDevice.getDeviceFromContext(gl);
		if (existingDevice) return existingDevice;
		if (!isWebGL(gl)) throw new Error("Invalid WebGL2RenderingContext");
		const createCanvasContext = props.createCanvasContext === true ? {} : props.createCanvasContext;
		return new WebGLDevice({
			...props,
			_handle: gl,
			createCanvasContext: {
				canvas: gl.canvas,
				autoResize: false,
				...createCanvasContext
			}
		});
	}
	async create(props = {}) {
		const { WebGLDevice } = await import("./webgl-device-DmZ5B3dw.js").then((n) => n.n);
		const promises = [];
		if (props.debugWebGL || props.debug) promises.push(loadWebGLDeveloperTools());
		if (props.debugSpectorJS) promises.push(loadSpectorJS(props));
		const results = await Promise.allSettled(promises);
		for (const result of results) if (result.status === "rejected") log.error(`Failed to initialize debug libraries ${result.reason}`)();
		try {
			const device = new WebGLDevice(props);
			log.groupCollapsed(LOG_LEVEL, `WebGLDevice ${device.id} created`)();
			const message = `\
${device._reused ? "Reusing" : "Created"} device with WebGL2 ${device.props.debug ? "debug " : ""}context: \
${device.info.vendor}, ${device.info.renderer} for canvas: ${device.canvasContext.id}`;
			log.probe(LOG_LEVEL, message)();
			log.table(LOG_LEVEL, device.info)();
			return device;
		} finally {
			log.groupEnd(LOG_LEVEL)();
			log.info(LOG_LEVEL, `%cWebGL call tracing: luma.log.set('debug-webgl') `, "color: white; background: blue; padding: 2px 6px; border-radius: 3px;")();
		}
	}
};
/** Check if supplied parameter is a WebGL2RenderingContext */
function isWebGL(gl) {
	if (typeof WebGL2RenderingContext !== "undefined" && gl instanceof WebGL2RenderingContext) return true;
	return Boolean(gl && typeof gl.createVertexArray === "function");
}
var webgl2Adapter = new WebGLAdapter();
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/deck.js
function noop() {}
var getCursor = ({ isDragging }) => isDragging ? "grabbing" : "grab";
var defaultProps = {
	id: "",
	width: "100%",
	height: "100%",
	style: null,
	viewState: null,
	initialViewState: null,
	pickingRadius: 0,
	pickAsync: "auto",
	layerFilter: null,
	parameters: {},
	parent: null,
	device: null,
	deviceProps: {},
	gl: null,
	canvas: null,
	layers: [],
	effects: [],
	views: null,
	controller: null,
	useDevicePixels: true,
	touchAction: "none",
	eventRecognizerOptions: {},
	_framebuffer: null,
	_animate: false,
	_pickable: true,
	_typedArrayManagerProps: {},
	_customRender: null,
	widgets: [],
	onDeviceInitialized: noop,
	onWebGLInitialized: noop,
	onResize: noop,
	onViewStateChange: noop,
	onInteractionStateChange: noop,
	onBeforeRender: noop,
	onAfterRender: noop,
	onLoad: noop,
	onError: (error) => defaultLogger.error(error.message, error.cause)(),
	onHover: null,
	onClick: null,
	onDragStart: null,
	onDrag: null,
	onDragEnd: null,
	_onMetrics: null,
	getCursor,
	getTooltip: null,
	debug: false,
	drawPickingColors: false
};
var Deck = class {
	constructor(props) {
		this.width = 0;
		this.height = 0;
		this.userData = {};
		this.device = null;
		this.canvas = null;
		this.viewManager = null;
		this.layerManager = null;
		this.effectManager = null;
		this.deckRenderer = null;
		this.deckPicker = null;
		this.eventManager = null;
		this.widgetManager = null;
		this.tooltip = null;
		this.animationLoop = null;
		this._canvasContext = null;
		this._deviceResizeHandler = null;
		this.cursorState = {
			isHovering: false,
			isDragging: false
		};
		this.stats = new Stats({ id: "deck.gl" });
		this.metrics = {
			fps: 0,
			setPropsTime: 0,
			layersCount: 0,
			drawLayersCount: 0,
			updateLayersCount: 0,
			updateAttributesCount: 0,
			updateAttributesTime: 0,
			framesRedrawn: 0,
			pickTime: 0,
			pickCount: 0,
			pickLayersCount: 0,
			gpuTime: 0,
			gpuTimePerFrame: 0,
			cpuTime: 0,
			cpuTimePerFrame: 0,
			bufferMemory: 0,
			textureMemory: 0,
			renderbufferMemory: 0,
			gpuMemory: 0
		};
		this._metricsCounter = 0;
		this._hoverPickSequence = 0;
		this._pointerDownPickSequence = 0;
		this._needsRedraw = "Initial render";
		this._pickRequest = {
			mode: "hover",
			x: -1,
			y: -1,
			radius: 0,
			event: null,
			unproject3D: false
		};
		/**
		* Pick and store the object under the pointer on `pointerdown`.
		* This object is reused for subsequent `onClick` and `onDrag*` callbacks.
		*/
		this._lastPointerDownInfo = null;
		this._lastPointerDownInfoPromise = null;
		/** Internal use only: event handler for pointerdown */
		this._onPointerMove = (event) => {
			const { _pickRequest } = this;
			if (event.type === "pointerleave") {
				_pickRequest.x = -1;
				_pickRequest.y = -1;
				_pickRequest.radius = 0;
			} else if (event.leftButton || event.rightButton) return;
			else {
				const pos = event.offsetCenter;
				if (!pos) return;
				_pickRequest.x = pos.x;
				_pickRequest.y = pos.y;
				_pickRequest.radius = this.props.pickingRadius;
			}
			if (this.layerManager) this.layerManager.context.mousePosition = {
				x: _pickRequest.x,
				y: _pickRequest.y
			};
			_pickRequest.event = event;
		};
		/** Internal use only: event handler for click & drag */
		this._onEvent = (event) => {
			const eventHandlerProp = EVENT_HANDLERS[event.type];
			const pos = event.offsetCenter;
			if (!eventHandlerProp || !pos || !this.layerManager) return;
			const layers = this.layerManager.getLayers();
			const internalPickingMode = this._getInternalPickingMode();
			if (!internalPickingMode) return;
			if (internalPickingMode === "sync") {
				const info = event.type === "click" && this._shouldUnproject3D(layers) ? this._getFirstPickedInfo(this._pickPointSync(this._getPointPickOptions(pos.x, pos.y, { unproject3D: true }, layers))) : this._getLastPointerDownPickingInfo(pos.x, pos.y, layers);
				this._dispatchPickingEvent(info, event);
				return;
			}
			(this._lastPointerDownInfoPromise || Promise.resolve(this._getLastPointerDownPickingInfo(pos.x, pos.y, layers))).then((info) => {
				this._dispatchPickingEvent(info, event);
			}).catch((error) => this.props.onError?.(error));
		};
		/** Internal use only: evnet handler for pointerdown */
		this._onPointerDown = (event) => {
			const pos = event.offsetCenter;
			if (!pos) return;
			const internalPickingMode = this._getInternalPickingMode();
			if (!internalPickingMode) return;
			const layers = this.layerManager?.getLayers() || [];
			const pointerDownPickSequence = ++this._pointerDownPickSequence;
			if (internalPickingMode === "sync") {
				const pickedInfo = this._pickPointSync({
					x: pos.x,
					y: pos.y,
					radius: this.props.pickingRadius
				});
				const info = this._getFirstPickedInfo(pickedInfo);
				this._lastPointerDownInfo = info;
				this._lastPointerDownInfoPromise = Promise.resolve(info);
				return;
			}
			const pickPromise = this._pickPointAsync(this._getPointPickOptions(pos.x, pos.y, {}, layers)).then((pickResult) => this._getFirstPickedInfo(pickResult)).then((info) => {
				if (pointerDownPickSequence === this._pointerDownPickSequence) this._lastPointerDownInfo = info;
				return info;
			}).catch((error) => {
				this.props.onError?.(error);
				const fallbackInfo = this.deckPicker && this.viewManager ? this._getLastPointerDownPickingInfo(pos.x, pos.y, layers) : {};
				if (pointerDownPickSequence === this._pointerDownPickSequence) this._lastPointerDownInfo = fallbackInfo;
				return fallbackInfo;
			});
			this._lastPointerDownInfo = null;
			this._lastPointerDownInfoPromise = pickPromise;
		};
		const initialProps = props;
		this.props = {
			...defaultProps,
			...props
		};
		props = this.props;
		if (props.viewState && props.initialViewState) defaultLogger.warn("View state tracking is disabled. Use either `initialViewState` for auto update or `viewState` for manual update.")();
		this.viewState = this.props.initialViewState;
		if (props.device) {
			this.device = props.device;
			this._setDeviceCanvasContext(props.device);
		}
		let deviceOrPromise = this.device;
		if (!deviceOrPromise && props.gl) {
			if (props.gl instanceof WebGLRenderingContext) defaultLogger.error("WebGL1 context not supported.")();
			deviceOrPromise = webgl2Adapter.attach(props.gl, {
				_cacheShaders: true,
				_cachePipelines: true,
				...this.props.deviceProps
			});
		}
		if (!deviceOrPromise) deviceOrPromise = this._createDevice(props);
		this.animationLoop = this._createAnimationLoop(deviceOrPromise, props);
		this.setProps(initialProps);
		if (props._typedArrayManagerProps) typed_array_manager_default.setOptions(props._typedArrayManagerProps);
		this.animationLoop.start();
	}
	/** Stop rendering and dispose all resources */
	finalize() {
		this._restoreDeviceResizeHandler();
		this.animationLoop?.stop();
		this.animationLoop?.destroy();
		this.animationLoop = null;
		this._hoverPickSequence++;
		this._pointerDownPickSequence++;
		this._lastPointerDownInfo = null;
		this._lastPointerDownInfoPromise = null;
		this.layerManager?.finalize();
		this.layerManager = null;
		this.viewManager?.finalize();
		this.viewManager = null;
		this.effectManager?.finalize();
		this.effectManager = null;
		this.deckRenderer?.finalize();
		this.deckRenderer = null;
		this.deckPicker?.finalize();
		this.deckPicker = null;
		this.eventManager?.destroy();
		this.eventManager = null;
		this.widgetManager?.finalize();
		this.widgetManager = null;
		if (!this.props.canvas && !this.props.device && !this.props.gl && this.canvas) {
			this.canvas.parentElement?.removeChild(this.canvas);
			this.canvas = null;
		}
		this._canvasContext = null;
	}
	/** Partially update props */
	setProps(props) {
		this.stats.get("setProps Time").timeStart();
		if ("onLayerHover" in props) defaultLogger.removed("onLayerHover", "onHover")();
		if ("onLayerClick" in props) defaultLogger.removed("onLayerClick", "onClick")();
		if (props.initialViewState && !deepEqual(this.props.initialViewState, props.initialViewState, 3)) this.viewState = props.initialViewState;
		Object.assign(this.props, props);
		this._validateInternalPickingMode();
		this._setCanvasSize(this.props);
		const resolvedProps = Object.create(this.props);
		Object.assign(resolvedProps, {
			views: this._getViews(),
			width: this.width,
			height: this.height,
			viewState: this._getViewState()
		});
		if (props.device && props.device.id !== this.device?.id) {
			const canvasContext = props.device.getDefaultCanvasContext();
			this.animationLoop?.stop();
			if (this.canvas !== canvasContext.canvas) {
				this.canvas?.remove();
				this.eventManager?.destroy();
				this.canvas = null;
			}
			this._setDeviceCanvasContext(props.device);
			defaultLogger.log(`recreating animation loop for new device! id=${props.device.id}`)();
			this.animationLoop = this._createAnimationLoop(props.device, props);
			this.animationLoop.start();
		}
		this.animationLoop?.setProps(resolvedProps);
		if (props.useDevicePixels !== void 0 && this._canvasContext?.setProps) this._canvasContext.setProps({ useDevicePixels: props.useDevicePixels });
		if (this.layerManager) {
			this.viewManager.setProps(resolvedProps);
			this.layerManager.activateViewport(this.getViewports()[0]);
			this.layerManager.setProps(resolvedProps);
			this.effectManager.setProps(resolvedProps);
			this.deckRenderer.setProps(resolvedProps);
			this.deckPicker.setProps(resolvedProps);
			this.widgetManager.setProps(resolvedProps);
		}
		this.stats.get("setProps Time").timeEnd();
	}
	/**
	* Check if a redraw is needed
	* @returns `false` or a string summarizing the redraw reason
	*/
	needsRedraw(opts = { clearRedrawFlags: false }) {
		if (!this.layerManager) return false;
		if (this.props._animate) return "Deck._animate";
		let redraw = this._needsRedraw;
		if (opts.clearRedrawFlags) this._needsRedraw = false;
		const viewManagerNeedsRedraw = this.viewManager.needsRedraw(opts);
		const layerManagerNeedsRedraw = this.layerManager.needsRedraw(opts);
		const effectManagerNeedsRedraw = this.effectManager.needsRedraw(opts);
		const deckRendererNeedsRedraw = this.deckRenderer.needsRedraw(opts);
		redraw = redraw || viewManagerNeedsRedraw || layerManagerNeedsRedraw || effectManagerNeedsRedraw || deckRendererNeedsRedraw;
		return redraw;
	}
	/**
	* Redraw the GL context
	* @param reason If not provided, only redraw if deemed necessary. Otherwise redraw regardless of internal states.
	* @returns
	*/
	redraw(reason) {
		if (!this.layerManager) return;
		let redrawReason = this.needsRedraw({ clearRedrawFlags: true });
		redrawReason = reason || redrawReason;
		if (!redrawReason) return;
		this.stats.get("Redraw Count").incrementCount();
		if (this.props._customRender) this.props._customRender(redrawReason);
		else this._drawLayers(redrawReason);
	}
	/** Flag indicating that the Deck instance has initialized its resources and it's safe to call public methods. */
	get isInitialized() {
		return this.viewManager !== null;
	}
	/** Get a list of views that are currently rendered */
	getViews() {
		assert$1(this.viewManager);
		return this.viewManager.views;
	}
	/** Get a view by id */
	getView(viewId) {
		assert$1(this.viewManager);
		return this.viewManager.getView(viewId);
	}
	/** Get a list of viewports that are currently rendered.
	* @param rect If provided, only returns viewports within the given bounding box.
	*/
	getViewports(rect) {
		assert$1(this.viewManager);
		return this.viewManager.getViewports(rect);
	}
	/** Get the current canvas element. */
	getCanvas() {
		return this.canvas;
	}
	/** Query the object rendered on top at a given point */
	async pickObjectAsync(opts) {
		const infos = (await this._pickAsync("pickObjectAsync", "pickObject Time", opts)).result;
		return infos.length ? infos[0] : null;
	}
	/**
	* Query all objects rendered on top within a bounding box
	* @note Caveat: this method performs multiple async GPU queries, so state could potentially change between calls.
	*/
	async pickObjectsAsync(opts) {
		return await this._pickAsync("pickObjectsAsync", "pickObjects Time", opts);
	}
	/**
	* Query the object rendered on top at a given point
	* @deprecated WebGL only. Use `pickObjectsAsync` instead
	*/
	pickObject(opts) {
		const infos = this._pick("pickObject", "pickObject Time", opts).result;
		return infos.length ? infos[0] : null;
	}
	/**
	* Query all rendered objects at a given point
	* @deprecated WebGL only. Use `pickObjectsAsync` instead
	*/
	pickMultipleObjects(opts) {
		opts.depth = opts.depth || 10;
		return this._pick("pickObject", "pickMultipleObjects Time", opts).result;
	}
	/**
	* Query all objects rendered on top within a bounding box
	* @deprecated WebGL only. Use `pickObjectsAsync` instead
	*/
	pickObjects(opts) {
		return this._pick("pickObjects", "pickObjects Time", opts);
	}
	/**
	* Internal method used by controllers to pick 3D position at a screen coordinate
	* @private
	*/
	_pickPositionForController(x, y) {
		if (this._getInternalPickingMode() !== "sync") return null;
		return this.pickObject({
			x,
			y,
			radius: 0,
			unproject3D: true
		});
	}
	/** Experimental
	* Add a global resource for sharing among layers
	*/
	_addResources(resources, forceUpdate = false) {
		for (const id in resources) this.layerManager.resourceManager.add({
			resourceId: id,
			data: resources[id],
			forceUpdate
		});
	}
	/** Experimental
	* Remove a global resource
	*/
	_removeResources(resourceIds) {
		for (const id of resourceIds) this.layerManager.resourceManager.remove(id);
	}
	/** Experimental
	* Register a default effect. Effects will be sorted by order, those with a low order will be rendered first
	*/
	_addDefaultEffect(effect) {
		this.effectManager.addDefaultEffect(effect);
	}
	_addDefaultShaderModule(module) {
		this.layerManager.addDefaultShaderModule(module);
	}
	_removeDefaultShaderModule(module) {
		this.layerManager?.removeDefaultShaderModule(module);
	}
	_resolveInternalPickingMode() {
		const { pickAsync } = this.props;
		const deviceType = this.device?.type || this.props.deviceProps?.type;
		if (pickAsync === "auto") return deviceType === "webgpu" ? "async" : "sync";
		if (pickAsync === "sync" && deviceType === "webgpu") throw new Error("`pickAsync: \"sync\"` is not supported when Deck is using a WebGPU device.");
		return pickAsync;
	}
	_getInternalPickingMode() {
		try {
			return this._resolveInternalPickingMode();
		} catch (error) {
			this.props.onError?.(error);
			return null;
		}
	}
	_validateInternalPickingMode() {
		this._getInternalPickingMode();
	}
	_getFirstPickedInfo({ result, emptyInfo }) {
		return result[0] || emptyInfo;
	}
	_shouldUnproject3D(layers = this.layerManager?.getLayers() || []) {
		return layers.some((layer) => layer.props.pickable === "3d");
	}
	_getPointPickOptions(x, y, opts = {}, layers = this.layerManager?.getLayers() || []) {
		return {
			x,
			y,
			radius: this.props.pickingRadius,
			unproject3D: this._shouldUnproject3D(layers),
			...opts
		};
	}
	_pickPointSync(opts) {
		return this._pick("pickObject", "pickObject Time", opts);
	}
	_pickPointAsync(opts) {
		return this._pickAsync("pickObjectAsync", "pickObject Time", opts);
	}
	_getLastPointerDownPickingInfo(x, y, layers = this.layerManager?.getLayers() || []) {
		return this.deckPicker.getLastPickedObject({
			x,
			y,
			layers,
			viewports: this.getViewports({
				x,
				y
			})
		}, this._lastPointerDownInfo);
	}
	_applyHoverCallbacks({ result, emptyInfo }, event) {
		if (!this.widgetManager) return;
		this.cursorState.isHovering = result.length > 0;
		let pickedInfo = emptyInfo;
		let handled = false;
		for (const info of result) {
			pickedInfo = info;
			handled = info.layer?.onHover(info, event) || handled;
		}
		if (!handled) {
			this.props.onHover?.(pickedInfo, event);
			this.widgetManager.onHover(pickedInfo, event);
		}
	}
	_dispatchPickingEvent(info, event) {
		if (!this.layerManager || !this.widgetManager) return;
		const eventHandlerProp = EVENT_HANDLERS[event.type];
		if (!eventHandlerProp) return;
		const { layer } = info;
		const layerHandler = layer && (layer[eventHandlerProp] || layer.props[eventHandlerProp]);
		const rootHandler = this.props[eventHandlerProp];
		let handled = false;
		if (layerHandler) handled = layerHandler.call(layer, info, event);
		if (!handled) {
			rootHandler?.(info, event);
			this.widgetManager.onEvent(info, event);
		}
	}
	_pickAsync(method, statKey, opts) {
		assert$1(this.deckPicker);
		const { stats } = this;
		stats.get("Pick Count").incrementCount();
		stats.get(statKey).timeStart();
		const infos = this.deckPicker[method]({
			layers: this.layerManager.getLayers(opts),
			views: this.viewManager.getViews(),
			viewports: this.getViewports(opts),
			onViewportActive: this.layerManager.activateViewport,
			effects: this.effectManager.getEffects(),
			...opts,
			canvasContext: this._canvasContext || void 0
		});
		stats.get(statKey).timeEnd();
		return infos;
	}
	_pick(method, statKey, opts) {
		assert$1(this.deckPicker);
		const { stats } = this;
		stats.get("Pick Count").incrementCount();
		stats.get(statKey).timeStart();
		const infos = this.deckPicker[method]({
			layers: this.layerManager.getLayers(opts),
			views: this.viewManager.getViews(),
			viewports: this.getViewports(opts),
			onViewportActive: this.layerManager.activateViewport,
			effects: this.effectManager.getEffects(),
			...opts,
			canvasContext: this._canvasContext || void 0
		});
		stats.get(statKey).timeEnd();
		return infos;
	}
	/** Resolve props.canvas to element */
	_createCanvas(props) {
		let canvas = props.canvas;
		if (typeof canvas === "string") {
			canvas = document.getElementById(canvas);
			assert$1(canvas);
		}
		if (!canvas) {
			canvas = document.createElement("canvas");
			canvas.id = props.id || "deckgl-overlay";
			if (props.width && typeof props.width === "number") canvas.width = props.width;
			if (props.height && typeof props.height === "number") canvas.height = props.height;
			(props.parent || document.body).appendChild(canvas);
		}
		Object.assign(canvas.style, props.style);
		return canvas;
	}
	_setCanvasContext(canvasContext) {
		this._canvasContext = canvasContext;
		if ("style" in canvasContext.canvas) this.canvas = canvasContext.canvas;
	}
	_setDeviceCanvasContext(device, opts = {}) {
		const canvasContext = device.getDefaultCanvasContext();
		this._setCanvasContext(canvasContext);
		this._setDeviceResizeHandler(device, opts);
	}
	_setDeviceResizeHandler(device, opts = {}) {
		const syncDrawingBuffer = Boolean(opts.syncDrawingBuffer);
		if (this._deviceResizeHandler?.device === device) {
			this._deviceResizeHandler.syncDrawingBuffer = syncDrawingBuffer;
			return;
		}
		this._restoreDeviceResizeHandler();
		const onResize = (canvasContext) => {
			if (canvasContext === this._canvasContext && this._canvasContext) this._onCanvasContextResize(this._canvasContext, { syncDrawingBuffer: this._deviceResizeHandler?.syncDrawingBuffer });
		};
		device.props.onResize = onResize;
		this._deviceResizeHandler = {
			device,
			onResize,
			syncDrawingBuffer
		};
	}
	_restoreDeviceResizeHandler() {
		const resizeHandler = this._deviceResizeHandler;
		if (resizeHandler && resizeHandler.device.props?.onResize === resizeHandler.onResize) resizeHandler.device.props.onResize = noop;
		this._deviceResizeHandler = null;
	}
	/** Updates canvas width and/or height, if provided as props */
	_setCanvasSize(props) {
		if (!this.canvas) return;
		const { width, height } = props;
		if (width || width === 0) {
			const cssWidth = Number.isFinite(width) ? `${width}px` : width;
			this.canvas.style.width = cssWidth;
		}
		if (height || height === 0) {
			const cssHeight = Number.isFinite(height) ? `${height}px` : height;
			this.canvas.style.position = props.style?.position || "absolute";
			this.canvas.style.height = cssHeight;
		}
	}
	/**
	* Sync Deck viewport dimensions from the active canvas context.
	* luma.gl owns resize observation, DPR tracking and drawing buffer sizing for Deck-created
	* canvases. Attached WebGL contexts still need Deck to mirror external drawing-buffer changes.
	*/
	_updateCanvasSize(canvasContext = this._canvasContext) {
		const { canvas } = this;
		const [newWidth, newHeight] = canvasContext ? canvasContext.getCSSSize() : [canvas?.clientWidth ?? canvas?.width ?? 0, canvas?.clientHeight ?? canvas?.height ?? 0];
		if (newWidth !== this.width || newHeight !== this.height) {
			this.width = newWidth;
			this.height = newHeight;
			this.viewManager?.setProps({
				width: newWidth,
				height: newHeight
			});
			this.layerManager?.activateViewport(this.getViewports()[0]);
			this.props.onResize({
				width: newWidth,
				height: newHeight
			}, canvasContext || void 0);
		}
	}
	_onCanvasContextResize(canvasContext, opts = {}) {
		if (opts.syncDrawingBuffer) {
			const { width, height } = canvasContext.canvas;
			canvasContext.setDrawingBufferSize(width, height);
		}
		this._needsRedraw = "Canvas resized";
		this._updateCanvasSize(canvasContext);
	}
	_createAnimationLoop(deviceOrPromise, props) {
		const { gl, onError } = props;
		return new AnimationLoop({
			device: deviceOrPromise,
			autoResizeDrawingBuffer: !gl,
			autoResizeViewport: false,
			onInitialize: (context) => this._setDevice(context.device),
			onRender: this._onRenderFrame.bind(this),
			onError
		});
	}
	_createDevice(props) {
		const canvasContextUserProps = this.props.deviceProps?.createCanvasContext;
		const canvasContextProps = typeof canvasContextUserProps === "object" ? canvasContextUserProps : void 0;
		const deviceProps = {
			adapters: [],
			_cacheShaders: true,
			_cachePipelines: true,
			...props.deviceProps
		};
		if (!deviceProps.adapters.includes(webgl2Adapter)) deviceProps.adapters.push(webgl2Adapter);
		const defaultCanvasProps = { alphaMode: this.props.deviceProps?.type === "webgpu" ? "premultiplied" : void 0 };
		return luma.createDevice({
			_reuseDevices: true,
			type: "webgl",
			...deviceProps,
			createCanvasContext: {
				...defaultCanvasProps,
				...canvasContextProps,
				canvas: this._createCanvas(props),
				useDevicePixels: this.props.useDevicePixels,
				autoResize: true
			}
		});
	}
	_getViewState() {
		return this.props.viewState || this.viewState;
	}
	_getViews() {
		const { views } = this.props;
		const normalizedViews = Array.isArray(views) ? views : views ? [views] : [new MapView({ id: "default-view" })];
		if (normalizedViews.length && this.props.controller) normalizedViews[0].props.controller = this.props.controller;
		return normalizedViews;
	}
	_onContextLost() {
		const { onError } = this.props;
		if (this.animationLoop && onError) onError(/* @__PURE__ */ new Error("WebGL context is lost"));
	}
	/** Actually run picking */
	_pickAndCallback() {
		const { _pickRequest } = this;
		if (_pickRequest.event) {
			const event = _pickRequest.event;
			const layers = this.layerManager?.getLayers() || [];
			const pickOptions = this._getPointPickOptions(_pickRequest.x, _pickRequest.y, {
				radius: _pickRequest.radius,
				mode: _pickRequest.mode
			}, layers);
			const internalPickingMode = this._getInternalPickingMode();
			const hoverPickSequence = ++this._hoverPickSequence;
			_pickRequest.event = null;
			if (!internalPickingMode) return;
			if (internalPickingMode === "sync") {
				this._applyHoverCallbacks(this._pickPointSync(pickOptions), event);
				return;
			}
			this._pickPointAsync(pickOptions).then(({ result, emptyInfo }) => {
				if (hoverPickSequence === this._hoverPickSequence) this._applyHoverCallbacks({
					result,
					emptyInfo
				}, event);
			}).catch((error) => this.props.onError?.(error));
		}
	}
	_updateCursor() {
		const container = this.props.parent || this.canvas;
		if (container) container.style.cursor = this.props.getCursor(this.cursorState);
	}
	_setDevice(device) {
		this.device = device;
		this._validateInternalPickingMode();
		if (!this.animationLoop) return;
		this._setDeviceCanvasContext(device, { syncDrawingBuffer: Boolean(this.props.gl && this.props.device !== device) });
		if (this.canvas && !this.canvas.isConnected && this.props.parent) this.props.parent.insertBefore(this.canvas, this.props.parent.firstChild);
		if (this.device.type === "webgl") this.device.setParametersWebGL({
			blend: true,
			blendFunc: [
				770,
				771,
				1,
				771
			],
			polygonOffsetFill: true,
			depthTest: true,
			depthFunc: 515
		});
		this.props.onDeviceInitialized(this.device);
		if (this.device.type === "webgl") this.props.onWebGLInitialized(this.device.gl);
		const timeline = new Timeline();
		timeline.play();
		this.animationLoop.attachTimeline(timeline);
		const eventRoot = this.props.parent?.querySelector(".deck-events-root") || this.canvas;
		this.eventManager = new EventManager(eventRoot, {
			touchAction: this.props.touchAction,
			recognizers: Object.keys(RECOGNIZERS).map((eventName) => {
				const [RecognizerConstructor, defaultOptions, recognizeWith, requireFailure] = RECOGNIZERS[eventName];
				const optionsOverride = this.props.eventRecognizerOptions?.[eventName];
				return {
					recognizer: new RecognizerConstructor({
						...defaultOptions,
						...optionsOverride,
						event: eventName
					}),
					recognizeWith,
					requireFailure
				};
			}),
			events: {
				pointerdown: this._onPointerDown,
				pointermove: this._onPointerMove,
				pointerleave: this._onPointerMove
			}
		});
		for (const eventType in EVENT_HANDLERS) this.eventManager.on(eventType, this._onEvent);
		this.viewManager = new ViewManager({
			timeline,
			eventManager: this.eventManager,
			onViewStateChange: this._onViewStateChange.bind(this),
			onInteractionStateChange: this._onInteractionStateChange.bind(this),
			pickPosition: this._pickPositionForController.bind(this),
			views: this._getViews(),
			viewState: this._getViewState(),
			width: this.width,
			height: this.height
		});
		const viewport = this.viewManager.getViewports()[0];
		this.layerManager = new LayerManager(this.device, {
			deck: this,
			stats: this.stats,
			viewport,
			timeline
		});
		this.effectManager = new EffectManager({
			deck: this,
			device: this.device
		});
		this.deckRenderer = new DeckRenderer(this.device, { stats: this.stats });
		this.deckPicker = new DeckPicker(this.device, { stats: this.stats });
		const widgetParent = this.props.parent?.querySelector(".deck-widgets-root") || this.canvas?.parentElement;
		this.widgetManager = new WidgetManager({
			deck: this,
			parentElement: widgetParent
		});
		this.widgetManager.addDefault(new TooltipWidget());
		this.setProps({});
		this._updateCanvasSize(this._canvasContext);
		this.props.onLoad();
	}
	/** Internal only: default render function (redraw all layers and views) */
	_drawLayers(redrawReason, renderOptions) {
		const { device, gl } = this.layerManager.context;
		this.props.onBeforeRender({
			device,
			gl
		});
		const opts = {
			target: this.props._framebuffer,
			layers: this.layerManager.getLayers(),
			viewports: this.viewManager.getViewports(),
			onViewportActive: this.layerManager.activateViewport,
			views: this.viewManager.getViews(),
			pass: "screen",
			effects: this.effectManager.getEffects(),
			...renderOptions
		};
		this.deckRenderer?.renderLayers(opts);
		if (opts.pass === "screen") this.widgetManager.onRedraw({
			viewports: opts.viewports,
			layers: opts.layers
		});
		this.props.onAfterRender({
			device,
			gl
		});
	}
	_onRenderFrame() {
		this._getFrameStats();
		if (this._metricsCounter++ % 60 === 0) {
			this._getMetrics();
			this.stats.reset();
			defaultLogger.table(4, this.metrics)();
			if (this.props._onMetrics) this.props._onMetrics(this.metrics);
		}
		this._updateCursor();
		this.layerManager.updateLayers();
		this._pickAndCallback();
		this.redraw();
		if (this.viewManager) this.viewManager.updateViewStates();
	}
	_onViewStateChange(params) {
		const viewState = this.props.onViewStateChange(params) || params.viewState;
		if (this.viewState) {
			this.viewState = {
				...this.viewState,
				[params.viewId]: viewState
			};
			if (!this.props.viewState) {
				if (this.viewManager) this.viewManager.setProps({ viewState: this.viewState });
			}
		}
	}
	_onInteractionStateChange(interactionState) {
		this.cursorState.isDragging = interactionState.isDragging || false;
		this.props.onInteractionStateChange(interactionState);
	}
	_getFrameStats() {
		const { stats } = this;
		stats.get("frameRate").timeEnd();
		stats.get("frameRate").timeStart();
		const animationLoopStats = this.animationLoop.stats;
		stats.get("GPU Time").addTime(animationLoopStats.get("GPU Time").lastTiming);
		stats.get("CPU Time").addTime(animationLoopStats.get("CPU Time").lastTiming);
	}
	_getMetrics() {
		const { metrics, stats } = this;
		metrics.fps = stats.get("frameRate").getHz();
		metrics.setPropsTime = stats.get("setProps Time").time;
		metrics.updateAttributesTime = stats.get("Update Attributes").time;
		metrics.framesRedrawn = stats.get("Redraw Count").count;
		metrics.pickTime = stats.get("pickObject Time").time + stats.get("pickMultipleObjects Time").time + stats.get("pickObjects Time").time;
		metrics.pickCount = stats.get("Pick Count").count;
		metrics.layersCount = this.layerManager?.layers.length ?? 0;
		metrics.drawLayersCount = stats.get("Layers rendered").lastSampleCount;
		metrics.pickLayersCount = stats.get("Layers picked").lastSampleCount;
		metrics.updateLayersCount = stats.get("Layer updates").count;
		metrics.updateAttributesCount = stats.get("Attributes updated").count;
		metrics.gpuTime = stats.get("GPU Time").time;
		metrics.cpuTime = stats.get("CPU Time").time;
		metrics.gpuTimePerFrame = stats.get("GPU Time").getAverageTime();
		metrics.cpuTimePerFrame = stats.get("CPU Time").getAverageTime();
		const memoryStats = luma.stats.get("GPU Time and Memory");
		metrics.bufferMemory = memoryStats.get("Buffer Memory").count;
		metrics.textureMemory = memoryStats.get("Texture Memory").count;
		metrics.renderbufferMemory = memoryStats.get("Renderbuffer Memory").count;
		metrics.gpuMemory = memoryStats.get("GPU Memory").count;
	}
};
Deck.defaultProps = defaultProps;
Deck.VERSION = VERSION;
//#endregion
//#region node_modules/@deck.gl/core/dist/controllers/globe-controller.js
var DEGREES_TO_RADIANS$1 = Math.PI / 180;
var RADIANS_TO_DEGREES = 180 / Math.PI;
function degreesToPixels(angle, zoom = 0) {
	const radians = Math.min(180, angle) * DEGREES_TO_RADIANS$1;
	return 256 * 2 * Math.sin(radians / 2) * Math.pow(2, zoom);
}
function pixelsToDegrees(pixels, zoom = 0) {
	const size = pixels / Math.pow(2, zoom);
	return Math.asin(Math.min(1, size / 256 / 2)) * 2 * RADIANS_TO_DEGREES;
}
var GlobeState = class extends MapState {
	constructor(options) {
		const { startPanPos, ...mapStateOptions } = options;
		mapStateOptions.normalize = false;
		super(mapStateOptions);
		if (startPanPos !== void 0) this._state.startPanPos = startPanPos;
	}
	panStart({ pos }) {
		const { latitude, longitude, zoom } = this.getViewportProps();
		return this._getUpdatedState({
			startPanLngLat: [longitude, latitude],
			startPanPos: pos,
			startZoom: zoom
		});
	}
	pan({ pos, startPos }) {
		const state = this.getState();
		const startPanLngLat = state.startPanLngLat || this._unproject(startPos);
		if (!startPanLngLat) return this;
		const startZoom = state.startZoom ?? this.getViewportProps().zoom;
		const startPanPos = state.startPanPos || startPos;
		const coords = [
			startPanLngLat[0],
			startPanLngLat[1],
			startZoom
		];
		const newProps = this.makeViewport(this.getViewportProps()).panByPosition(coords, pos, startPanPos);
		return this._getUpdatedState(newProps);
	}
	panEnd() {
		return this._getUpdatedState({
			startPanLngLat: null,
			startPanPos: null,
			startZoom: null
		});
	}
	zoom({ scale }) {
		const zoom = (this.getState().startZoom || this.getViewportProps().zoom) + Math.log2(scale);
		return this._getUpdatedState({ zoom });
	}
	applyConstraints(props) {
		const { longitude, latitude, maxBounds } = props;
		props.zoom = this._constrainZoom(props.zoom, props);
		if (longitude < -180 || longitude > 180) props.longitude = mod(longitude + 180, 360) - 180;
		props.latitude = clamp(latitude, -MAX_LATITUDE, MAX_LATITUDE);
		if (maxBounds) {
			props.longitude = clamp(props.longitude, maxBounds[0][0], maxBounds[1][0]);
			props.latitude = clamp(props.latitude, maxBounds[0][1], maxBounds[1][1]);
		}
		if (maxBounds) {
			const effectiveZoom = props.zoom - zoomAdjust(latitude);
			const lngSpan = maxBounds[1][0] - maxBounds[0][0];
			const latSpan = maxBounds[1][1] - maxBounds[0][1];
			if (latSpan > 0 && latSpan < 85.051129 * 2) {
				const halfHeightDegrees = Math.min(pixelsToDegrees(props.height, effectiveZoom), latSpan) / 2;
				props.latitude = clamp(props.latitude, maxBounds[0][1] + halfHeightDegrees, maxBounds[1][1] - halfHeightDegrees);
			}
			if (lngSpan > 0 && lngSpan < 360) {
				const halfWidthDegrees = Math.min(pixelsToDegrees(props.width / Math.cos(props.latitude * DEGREES_TO_RADIANS$1), effectiveZoom), lngSpan) / 2;
				props.longitude = clamp(props.longitude, maxBounds[0][0] + halfWidthDegrees, maxBounds[1][0] - halfWidthDegrees);
			}
		}
		if (props.latitude !== latitude) props.zoom += zoomAdjust(props.latitude) - zoomAdjust(latitude);
		return props;
	}
	_constrainZoom(zoom, props) {
		props || (props = this.getViewportProps());
		const { latitude, maxZoom, maxBounds } = props;
		let { minZoom } = props;
		const ZOOM0 = zoomAdjust(0);
		const zoomAdjustment = zoomAdjust(latitude) - ZOOM0;
		if (maxBounds !== null && props.width > 0 && props.height > 0) {
			const minLatitude = maxBounds[0][1];
			const maxLatitude = maxBounds[1][1];
			const fitLatitude = Math.sign(minLatitude) === Math.sign(maxLatitude) ? Math.min(Math.abs(minLatitude), Math.abs(maxLatitude)) : 0;
			const w = degreesToPixels(maxBounds[1][0] - maxBounds[0][0]) * Math.cos(fitLatitude * DEGREES_TO_RADIANS$1);
			const h = degreesToPixels(maxBounds[1][1] - maxBounds[0][1]);
			if (w > 0) minZoom = Math.max(minZoom, Math.log2(props.width / w) + ZOOM0);
			if (h > 0) minZoom = Math.max(minZoom, Math.log2(props.height / h) + ZOOM0);
			if (minZoom > maxZoom) minZoom = maxZoom;
		}
		return clamp(zoom, minZoom + zoomAdjustment, maxZoom + zoomAdjustment);
	}
};
var GlobeController = class extends Controller {
	constructor() {
		super(...arguments);
		this.ControllerState = GlobeState;
		this.transition = {
			transitionDuration: 300,
			transitionInterpolator: new LinearInterpolator([
				"longitude",
				"latitude",
				"zoom"
			])
		};
		this.dragMode = "pan";
	}
	setProps(props) {
		super.setProps(props);
		this.dragRotate = false;
		this.touchRotate = false;
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/views/globe-view.js
var GLOBE_VIEW_DEFAULT_PARAMETERS = { cullMode: "back" };
var GlobeView = class extends View {
	constructor(props = {}) {
		super({
			...props,
			parameters: {
				...GLOBE_VIEW_DEFAULT_PARAMETERS,
				...props.parameters
			}
		});
	}
	getViewportType(viewState) {
		return viewState.zoom > 12 ? WebMercatorViewport : GlobeViewport;
	}
	get ControllerType() {
		return GlobeController;
	}
};
GlobeView.displayName = "GlobeView";
//#endregion
//#region node_modules/@deck.gl/mapbox/dist/mapbox-layer-group.js
var MapboxLayerGroup = class {
	constructor(props) {
		assert$1(props.id, "id is required");
		this.id = props.id;
		this.type = "custom";
		this.renderingMode = props.renderingMode || "3d";
		this.slot = props.slot;
		this.beforeId = props.beforeId;
		this.map = null;
	}
	onAdd(map, gl) {
		this.map = map;
	}
	render(gl, renderParameters) {
		if (!this.map) return;
		drawLayerGroup(this.map.__deck, this.map, this, renderParameters);
	}
};
//#endregion
//#region node_modules/@deck.gl/mapbox/dist/resolve-layer-groups.js
var UNDEFINED_BEFORE_ID = "__UNDEFINED__";
function getLayerGroupId(layer) {
	if (layer.props.beforeId) return `deck-layer-group-before:${layer.props.beforeId}`;
	else if (layer.props.slot) return `deck-layer-group-slot:${layer.props.slot}`;
	return "deck-layer-group-last";
}
/** Group Deck layers into buckets (by beforeId or slot) and insert them
*  into the mapbox Map according to the user-defined order
**/
function resolveLayerGroups(map, oldLayers, newLayers) {
	if (!map || !map.style || !map.style._loaded) return;
	const layers = flatten(newLayers, Boolean);
	if (oldLayers !== newLayers) {
		const prevLayers = flatten(oldLayers, Boolean);
		const prevLayerGroupIds = new Set(prevLayers.map((l) => getLayerGroupId(l)));
		const newLayerGroupIds = new Set(layers.map((l) => getLayerGroupId(l)));
		for (const groupId of prevLayerGroupIds) if (!newLayerGroupIds.has(groupId)) {
			if (map.getLayer(groupId)) map.removeLayer(groupId);
		}
	}
	const layerGroups = {};
	for (const layer of layers) {
		const groupId = getLayerGroupId(layer);
		const mapboxGroup = map.getLayer(groupId);
		if (mapboxGroup) layerGroups[groupId] = mapboxGroup.implementation || mapboxGroup;
		else {
			const newGroup = new MapboxLayerGroup({
				id: groupId,
				slot: layer.props.slot,
				beforeId: layer.props.beforeId
			});
			layerGroups[groupId] = newGroup;
			map.addLayer(newGroup, layer.props.beforeId);
		}
	}
	const mapLayers = map.style._order;
	for (const [groupId, group] of Object.entries(layerGroups)) {
		const beforeId = group.beforeId || UNDEFINED_BEFORE_ID;
		const expectedGroupIndex = beforeId === UNDEFINED_BEFORE_ID ? mapLayers.length : mapLayers.indexOf(beforeId);
		if (expectedGroupIndex === -1) continue;
		if (mapLayers.indexOf(groupId) !== expectedGroupIndex - 1) {
			const moveBeforeId = beforeId === UNDEFINED_BEFORE_ID ? void 0 : beforeId;
			map.moveLayer(groupId, moveBeforeId);
		}
	}
}
//#endregion
//#region node_modules/@deck.gl/mapbox/dist/deck-utils.js
var MAPBOX_VIEW_ID = "mapbox";
var TILE_SIZE = 512;
var DEGREES_TO_RADIANS = Math.PI / 180;
function getDeckInstance({ map, deck }) {
	if (map.__deck) return map.__deck;
	const customRender = deck.props._customRender;
	const onLoad = deck.props.onLoad;
	const deckProps = {
		...deck.props,
		_customRender: () => {
			map.triggerRepaint();
			customRender?.("");
		}
	};
	deckProps.views || (deckProps.views = getDefaultView(map));
	Object.assign(deckProps, {
		width: null,
		height: null,
		touchAction: "unset",
		viewState: getViewState(map)
	});
	if (deck.isInitialized) watchMapMove(deck, map);
	else deckProps.onLoad = () => {
		onLoad?.();
		watchMapMove(deck, map);
	};
	deck.setProps(deckProps);
	map.__deck = deck;
	map.on("render", () => {
		if (deck.isInitialized) afterRender(deck, map);
	});
	return deck;
}
function watchMapMove(deck, map) {
	const _handleMapMove = () => {
		if (deck.isInitialized) onMapMove(deck, map);
		else map.off("move", _handleMapMove);
	};
	map.on("move", _handleMapMove);
}
function removeDeckInstance(map) {
	map.__deck?.finalize();
	map.__deck = null;
}
function getDefaultParameters(map, interleaved) {
	return interleaved ? {
		depthWriteEnabled: true,
		depthCompare: "less-equal",
		depthBias: 0,
		blend: true,
		blendColorSrcFactor: "src-alpha",
		blendColorDstFactor: "one-minus-src-alpha",
		blendAlphaSrcFactor: "one",
		blendAlphaDstFactor: "one-minus-src-alpha",
		blendColorOperation: "add",
		blendAlphaOperation: "add"
	} : {};
}
function drawLayerGroup(deck, map, group, renderParameters) {
	if (!deck.isInitialized) return;
	let { currentViewport } = deck.userData;
	let clearStack = false;
	if (!currentViewport) {
		currentViewport = getViewport(deck, map, renderParameters);
		deck.userData.currentViewport = currentViewport;
		clearStack = true;
	}
	if (!currentViewport) return;
	deck._drawLayers("mapbox-repaint", {
		viewports: [currentViewport],
		layerFilter: (params) => {
			if (deck.props.layerFilter && !deck.props.layerFilter(params)) return false;
			const layer = params.layer;
			if (layer.props.beforeId === group.beforeId && layer.props.slot === group.slot) return true;
			return false;
		},
		clearStack,
		clearCanvas: false
	});
}
function getProjection(map) {
	const projection = map.getProjection?.();
	const type = projection?.type || projection?.name;
	if (type === "globe") return "globe";
	if (type && type !== "mercator") throw new Error("Unsupported projection");
	return "mercator";
}
function getDefaultView(map) {
	if (getProjection(map) === "globe") return new GlobeView({ id: MAPBOX_VIEW_ID });
	return new MapView({ id: MAPBOX_VIEW_ID });
}
function getViewState(map) {
	const { lng, lat } = map.getCenter();
	const viewState = {
		longitude: (lng + 540) % 360 - 180,
		latitude: lat,
		zoom: map.getZoom(),
		bearing: map.getBearing(),
		pitch: map.getPitch(),
		padding: map.getPadding(),
		repeat: map.getRenderWorldCopies()
	};
	if (map.getTerrain?.()) centerCameraOnTerrain(map, viewState);
	return viewState;
}
function centerCameraOnTerrain(map, viewState) {
	if (map.getFreeCameraOptions) {
		const { position } = map.getFreeCameraOptions();
		if (!position || position.z === void 0) return;
		const height = map.transform.height;
		const { longitude, latitude, pitch } = viewState;
		const cameraX = position.x * TILE_SIZE;
		const cameraY = (1 - position.y) * TILE_SIZE;
		const cameraZ = position.z * TILE_SIZE;
		const center = lngLatToWorld$1([longitude, latitude]);
		const dx = cameraX - center[0];
		const dy = cameraY - center[1];
		const cameraToCenterDistanceGround = Math.sqrt(dx * dx + dy * dy);
		const pitchRadians = pitch * DEGREES_TO_RADIANS;
		const altitudePixels = 1.5 * height;
		const scale = pitchRadians < .001 ? altitudePixels * Math.cos(pitchRadians) / cameraZ : altitudePixels * Math.sin(pitchRadians) / cameraToCenterDistanceGround;
		viewState.zoom = Math.log2(scale);
		viewState.position = [
			0,
			0,
			(cameraZ - altitudePixels * Math.cos(pitchRadians) / scale) / unitsPerMeter(latitude)
		];
	} else if (typeof map.transform.elevation === "number") viewState.position = [
		0,
		0,
		map.transform.elevation
	];
}
function getViewport(deck, map, renderParameters) {
	const viewState = getViewState(map);
	const view = deck.getView("mapbox") || getDefaultView(map);
	if (renderParameters) view.props.nearZMultiplier = .2;
	const nearZ = renderParameters?.nearZ ?? map.transform._nearZ;
	const farZ = renderParameters?.farZ ?? map.transform._farZ;
	if (Number.isFinite(nearZ)) {
		viewState.nearZ = nearZ / map.transform.height;
		viewState.farZ = farZ / map.transform.height;
	}
	return view.makeViewport({
		width: deck.width,
		height: deck.height,
		viewState
	});
}
function afterRender(deck, map) {
	const hasNonMapboxLayers = flatten(deck.props.layers, Boolean).some((layer) => layer && !map.getLayer(getLayerGroupId(layer)));
	let viewports = deck.getViewports();
	const mapboxViewportIdx = viewports.findIndex((vp) => vp.id === MAPBOX_VIEW_ID);
	const hasNonMapboxViews = viewports.length > 1 || mapboxViewportIdx < 0;
	if (hasNonMapboxLayers || hasNonMapboxViews) {
		if (mapboxViewportIdx >= 0) {
			viewports = viewports.slice();
			const mapboxViewport = getViewport(deck, map);
			if (mapboxViewport) viewports[mapboxViewportIdx] = mapboxViewport;
			else viewports.splice(mapboxViewportIdx, 1);
		}
		deck._drawLayers("mapbox-repaint", {
			viewports,
			layerFilter: (params) => (!deck.props.layerFilter || deck.props.layerFilter(params)) && (params.viewport.id !== "mapbox" || !map.getLayer(getLayerGroupId(params.layer))),
			clearCanvas: false
		});
	} else {
		const device = deck.device;
		const gl = device?.gl;
		deck.props.onBeforeRender?.({
			device,
			gl
		});
		deck.props.onAfterRender?.({
			device,
			gl
		});
	}
	deck.userData.currentViewport = null;
}
function onMapMove(deck, map) {
	deck.setProps({ viewState: getViewState(map) });
	deck.needsRedraw({ clearRedrawFlags: true });
}
//#endregion
//#region node_modules/@deck.gl/mapbox/dist/mapbox-overlay.js
/**
* Implements Mapbox [IControl](https://docs.mapbox.com/mapbox-gl-js/api/markers/#icontrol) interface
* Renders deck.gl layers over the base map and automatically synchronizes with the map's camera
*/
var MapboxOverlay = class {
	constructor(props) {
		this._handleStyleChange = () => {
			this._resolveLayers(this._map, this._deck, this._props.layers, this._props.layers);
			if (!this._map) return;
			if (getProjection(this._map)) this._deck?.setProps({ views: this._getViews(this._map) });
		};
		this._updateContainerSize = () => {
			if (this._map && this._container) {
				const { clientWidth, clientHeight } = this._map.getContainer();
				Object.assign(this._container.style, {
					width: `${clientWidth}px`,
					height: `${clientHeight}px`
				});
			}
		};
		this._updateViewState = () => {
			const deck = this._deck;
			const map = this._map;
			if (deck && map) {
				deck.setProps({
					views: this._getViews(map),
					viewState: getViewState(map)
				});
				if (deck.isInitialized) deck.redraw();
			}
		};
		this._handleMouseEvent = (event) => {
			const deck = this._deck;
			if (!deck || !deck.isInitialized) return;
			const mockEvent = {
				type: event.type,
				offsetCenter: event.point,
				srcEvent: event
			};
			const lastDown = this._lastMouseDownPoint;
			if (!event.point && lastDown) {
				mockEvent.deltaX = event.originalEvent.clientX - lastDown.clientX;
				mockEvent.deltaY = event.originalEvent.clientY - lastDown.clientY;
				mockEvent.offsetCenter = {
					x: lastDown.x + mockEvent.deltaX,
					y: lastDown.y + mockEvent.deltaY
				};
			}
			switch (mockEvent.type) {
				case "mousedown":
					deck._onPointerDown(mockEvent);
					this._lastMouseDownPoint = {
						...event.point,
						clientX: event.originalEvent.clientX,
						clientY: event.originalEvent.clientY
					};
					break;
				case "dragstart":
					mockEvent.type = "panstart";
					deck._onEvent(mockEvent);
					break;
				case "drag":
					mockEvent.type = "panmove";
					deck._onEvent(mockEvent);
					break;
				case "dragend":
					mockEvent.type = "panend";
					deck._onEvent(mockEvent);
					break;
				case "click":
					mockEvent.tapCount = 1;
					deck._onEvent(mockEvent);
					break;
				case "dblclick":
					mockEvent.type = "click";
					mockEvent.tapCount = 2;
					deck._onEvent(mockEvent);
					break;
				case "mousemove":
					mockEvent.type = "pointermove";
					deck._onPointerMove(mockEvent);
					break;
				case "mouseout":
					mockEvent.type = "pointerleave";
					deck._onPointerMove(mockEvent);
					break;
				default: return;
			}
		};
		const { interleaved = false } = props;
		this._interleaved = interleaved;
		this._props = this.filterProps(props);
	}
	/** Filter out props to pass to Deck **/
	filterProps(props) {
		const { interleaved: _, useDevicePixels, ...deckProps } = props;
		if (!this._interleaved && useDevicePixels !== void 0) deckProps.useDevicePixels = useDevicePixels;
		return deckProps;
	}
	/** Update (partial) props of the underlying Deck instance. */
	setProps(props) {
		if (this._interleaved && props.layers) this._resolveLayers(this._map, this._deck, this._props.layers, props.layers);
		Object.assign(this._props, this.filterProps(props));
		if (this._deck && this._map) this._deck.setProps({
			...this._props,
			views: this._getViews(this._map),
			parameters: {
				...getDefaultParameters(this._map, this._interleaved),
				...this._props.parameters
			}
		});
	}
	/** Called when the control is added to a map */
	onAdd(map) {
		this._map = map;
		return this._interleaved ? this._onAddInterleaved(map) : this._onAddOverlaid(map);
	}
	_onAddOverlaid(map) {
		const container = document.createElement("div");
		Object.assign(container.style, {
			position: "absolute",
			left: 0,
			top: 0,
			textAlign: "initial",
			pointerEvents: "none"
		});
		this._container = container;
		this._deck = new Deck({
			...this._props,
			parent: container,
			deviceProps: {
				...this._props.deviceProps,
				createCanvasContext: {
					...typeof this._props.deviceProps?.createCanvasContext === "object" ? this._props.deviceProps.createCanvasContext : void 0,
					pixelSizeSource: "css-dpr"
				}
			},
			parameters: {
				...getDefaultParameters(map, false),
				...this._props.parameters
			},
			views: this._getViews(map),
			viewState: getViewState(map)
		});
		map.on("resize", this._updateContainerSize);
		map.on("render", this._updateViewState);
		map.on("mousedown", this._handleMouseEvent);
		map.on("dragstart", this._handleMouseEvent);
		map.on("drag", this._handleMouseEvent);
		map.on("dragend", this._handleMouseEvent);
		map.on("mousemove", this._handleMouseEvent);
		map.on("mouseout", this._handleMouseEvent);
		map.on("click", this._handleMouseEvent);
		map.on("dblclick", this._handleMouseEvent);
		this._updateContainerSize();
		return container;
	}
	_onAddInterleaved(map) {
		const gl = map.painter.context.gl;
		if (gl instanceof WebGLRenderingContext) defaultLogger.warn("Incompatible basemap library. See: https://deck.gl/docs/api-reference/mapbox/overview#compatibility")();
		this._deck = getDeckInstance({
			map,
			deck: new Deck({
				...this._props,
				views: this._getViews(map),
				gl,
				parameters: {
					...getDefaultParameters(map, true),
					...this._props.parameters
				}
			})
		});
		map.on("styledata", this._handleStyleChange);
		this._resolveLayers(map, this._deck, [], this._props.layers);
		return document.createElement("div");
	}
	_resolveLayers(map, _deck, prevLayers, newLayers) {
		resolveLayerGroups(map, prevLayers, newLayers);
	}
	/** Called when the control is removed from a map */
	onRemove() {
		const map = this._map;
		if (map) if (this._interleaved) this._onRemoveInterleaved(map);
		else this._onRemoveOverlaid(map);
		this._deck = void 0;
		this._map = void 0;
		this._container = void 0;
	}
	_onRemoveOverlaid(map) {
		map.off("resize", this._updateContainerSize);
		map.off("render", this._updateViewState);
		map.off("mousedown", this._handleMouseEvent);
		map.off("dragstart", this._handleMouseEvent);
		map.off("drag", this._handleMouseEvent);
		map.off("dragend", this._handleMouseEvent);
		map.off("mousemove", this._handleMouseEvent);
		map.off("mouseout", this._handleMouseEvent);
		map.off("click", this._handleMouseEvent);
		map.off("dblclick", this._handleMouseEvent);
		this._deck?.finalize();
	}
	_onRemoveInterleaved(map) {
		map.off("styledata", this._handleStyleChange);
		this._resolveLayers(map, this._deck, this._props.layers, []);
		removeDeckInstance(map);
	}
	getDefaultPosition() {
		return "top-left";
	}
	/** Forwards the Deck.pickObject method */
	pickObject(params) {
		assert$1(this._deck);
		return this._deck.pickObject(params);
	}
	/** Forwards the Deck.pickMultipleObjects method */
	pickMultipleObjects(params) {
		assert$1(this._deck);
		return this._deck.pickMultipleObjects(params);
	}
	/** Forwards the Deck.pickObjects method */
	pickObjects(params) {
		assert$1(this._deck);
		return this._deck.pickObjects(params);
	}
	/** Remove from map and releases all resources */
	finalize() {
		if (this._map) this._map.removeControl(this);
	}
	/** If interleaved: true, returns base map's canvas, otherwise forwards the Deck.getCanvas method. */
	getCanvas() {
		if (!this._map) return null;
		return this._interleaved ? this._map.getCanvas() : this._deck.getCanvas();
	}
	_getViews(map) {
		if (!this._props.views) return getDefaultView(map);
		const views = Array.isArray(this._props.views) ? this._props.views : [this._props.views];
		if (views.some((v) => v.id === "mapbox")) return this._props.views;
		return [getDefaultView(map), ...views];
	}
};
//#endregion
export { MapboxOverlay };

//# sourceMappingURL=@deck__gl_mapbox.js.map