import { r as __toESM } from "./chunk-B-1-B7_t.js";
import { t as require_react } from "./react.js";
import { t as require_react_dom } from "./react-dom-Br2l1Z8p.js";
//#region node_modules/@vis.gl/react-mapbox/dist/components/use-map.js
var import_react = /* @__PURE__ */ __toESM(require_react(), 1);
var MountedMapsContext = import_react.createContext(null);
var MapProvider = (props) => {
	const [maps, setMaps] = (0, import_react.useState)({});
	const onMapMount = (0, import_react.useCallback)((map, id = "default") => {
		setMaps((currMaps) => {
			if (id === "current") throw new Error("'current' cannot be used as map id");
			if (currMaps[id]) throw new Error(`Multiple maps with the same id: ${id}`);
			return {
				...currMaps,
				[id]: map
			};
		});
	}, []);
	const onMapUnmount = (0, import_react.useCallback)((id = "default") => {
		setMaps((currMaps) => {
			if (currMaps[id]) {
				const nextMaps = { ...currMaps };
				delete nextMaps[id];
				return nextMaps;
			}
			return currMaps;
		});
	}, []);
	return import_react.createElement(MountedMapsContext.Provider, { value: {
		maps,
		onMapMount,
		onMapUnmount
	} }, props.children);
};
function useMap() {
	const maps = (0, import_react.useContext)(MountedMapsContext)?.maps;
	const currentMap = (0, import_react.useContext)(MapContext);
	return (0, import_react.useMemo)(() => {
		return {
			...maps,
			current: currentMap?.map
		};
	}, [maps, currentMap]);
}
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/utils/transform.js
/**
* Capture a transform's current state
* @param transform
* @returns descriptor of the view state
*/
function transformToViewState(tr) {
	return {
		longitude: tr.center.lng,
		latitude: tr.center.lat,
		zoom: tr._seaLevelZoom ?? tr.zoom,
		pitch: tr.pitch,
		bearing: tr.bearing,
		padding: tr.padding,
		elevation: tr._centerAltitude
	};
}
/** Returns `true` if the given props can potentially override view state updates */
function isViewStateControlled(v) {
	return Number.isFinite(v.longitude) || Number.isFinite(v.latitude) || Number.isFinite(v.zoom) || Number.isFinite(v.pitch) || Number.isFinite(v.bearing);
}
/**
* Returns `true` if transform needs to be updated to match view state
*/
function compareViewStateWithTransform(tr, v) {
	if (Number.isFinite(v.longitude) && tr.center.lng !== v.longitude) return true;
	if (Number.isFinite(v.latitude) && tr.center.lat !== v.latitude) return true;
	if (Number.isFinite(v.bearing) && tr.bearing !== v.bearing) return true;
	if (Number.isFinite(v.pitch) && tr.pitch !== v.pitch) return true;
	if (Number.isFinite(v.zoom) && (tr._seaLevelZoom ?? tr.zoom) !== v.zoom) return true;
	if (v.padding && !tr.isPaddingEqual(v.padding)) return true;
	return false;
}
function noOp() {}
/**
* Mutate a transform to match the given view state. Should reverse `transformToViewState`
* @param transform
* @param viewState
*/
function applyViewStateToTransform(tr, v) {
	const constrain = tr._constrain;
	const calcMatrices = tr._calcMatrices;
	tr._constrain = noOp;
	tr._calcMatrices = noOp;
	if (Number.isFinite(v.bearing)) tr.bearing = v.bearing;
	if (Number.isFinite(v.pitch)) tr.pitch = v.pitch;
	if (v.padding && !tr.isPaddingEqual(v.padding)) tr.padding = v.padding;
	if (Number.isFinite(v.longitude) || Number.isFinite(v.latitude)) {
		const center = tr.center;
		tr._center = new center.constructor(v.longitude ?? center.lng, v.latitude ?? center.lat);
	}
	if (Number.isFinite(v.zoom)) {
		tr._centerAltitude = v.elevation ?? 0;
		if (tr.elevation) {
			tr._seaLevelZoom = v.zoom;
			const mercatorElevation = tr.pixelsPerMeter / tr.worldSize * tr._centerAltitude;
			const altitude = tr._mercatorZfromZoom(v.zoom);
			const minHeight = tr._mercatorZfromZoom(tr._maxZoom);
			const height = Math.max(altitude - mercatorElevation, minHeight);
			tr._setZoom(tr._zoomFromMercatorZ(height));
		} else {
			tr._seaLevelZoom = null;
			tr.zoom = v.zoom;
		}
	}
	tr._constrain = constrain;
	tr._calcMatrices = calcMatrices;
	if (!tr._unmodified) {
		tr._constrain();
		tr._calcMatrices();
	}
}
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/mapbox/proxy-transform.js
var unproxiedMethods = new Set([
	"_calcMatrices",
	"_calcFogMatrices",
	"_updateCameraState",
	"_updateSeaLevelZoom"
]);
function createProxyTransform(tr) {
	let internalUpdate = false;
	let reactViewState = {};
	/**
	* Reflects view state set by react props
	* This is the transform seen by painter, style etc.
	*/
	const controlledTransform = tr;
	/** Populated during camera move (handler/easeTo) if there is a discrepency between react props and proposed view state
	* This is the transform seen by Mapbox's input handlers
	*/
	let proposedTransform = null;
	return new Proxy(tr, {
		get(target, prop) {
			if (prop === "$reactViewState") return reactViewState;
			if (prop === "$proposedTransform") return proposedTransform;
			if (prop === "$internalUpdate") return internalUpdate;
			if (prop === "_setZoom") return (z) => {
				if (internalUpdate) proposedTransform?.[prop](z);
				if (!Number.isFinite(reactViewState.zoom)) controlledTransform[prop](z);
			};
			if (internalUpdate && prop === "_translateCameraConstrained" && isViewStateControlled(reactViewState)) proposedTransform = proposedTransform || controlledTransform.clone();
			if (unproxiedMethods.has(prop)) return function(...parms) {
				proposedTransform?.[prop](...parms);
				controlledTransform[prop](...parms);
			};
			if (internalUpdate && proposedTransform) return proposedTransform[prop];
			return controlledTransform[prop];
		},
		set(target, prop, value) {
			if (prop === "$reactViewState") {
				reactViewState = value;
				applyViewStateToTransform(controlledTransform, reactViewState);
				return true;
			}
			if (prop === "$proposedTransform") {
				proposedTransform = value;
				return true;
			}
			if (prop === "$internalUpdate") {
				internalUpdate = value;
				return true;
			}
			let controlledValue = value;
			if (prop === "center" || prop === "_center") {
				if (Number.isFinite(reactViewState.longitude) || Number.isFinite(reactViewState.latitude)) controlledValue = new value.constructor(reactViewState.longitude ?? value.lng, reactViewState.latitude ?? value.lat);
			} else if (prop === "zoom" || prop === "_zoom" || prop === "_seaLevelZoom") {
				if (Number.isFinite(reactViewState.zoom)) controlledValue = controlledTransform[prop];
			} else if (prop === "_centerAltitude") {
				if (Number.isFinite(reactViewState.elevation)) controlledValue = controlledTransform[prop];
			} else if (prop === "pitch" || prop === "_pitch") {
				if (Number.isFinite(reactViewState.pitch)) controlledValue = controlledTransform[prop];
			} else if (prop === "bearing" || prop === "rotation" || prop === "angle") {
				if (Number.isFinite(reactViewState.bearing)) controlledValue = controlledTransform[prop];
			}
			if (internalUpdate && controlledValue !== value) proposedTransform = proposedTransform || controlledTransform.clone();
			if (internalUpdate && proposedTransform) proposedTransform[prop] = value;
			controlledTransform[prop] = controlledValue;
			return true;
		}
	});
}
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/utils/style-utils.js
var refProps = [
	"type",
	"source",
	"source-layer",
	"minzoom",
	"maxzoom",
	"filter",
	"layout"
];
function normalizeStyle(style) {
	if (!style) return null;
	if (typeof style === "string") return style;
	if ("toJS" in style) style = style.toJS();
	if (!style.layers) return style;
	const layerIndex = {};
	for (const layer of style.layers) layerIndex[layer.id] = layer;
	const layers = style.layers.map((layer) => {
		let normalizedLayer = null;
		if ("interactive" in layer) {
			normalizedLayer = Object.assign({}, layer);
			delete normalizedLayer.interactive;
		}
		const layerRef = layerIndex[layer.ref];
		if (layerRef) {
			normalizedLayer = normalizedLayer || Object.assign({}, layer);
			delete normalizedLayer.ref;
			for (const propName of refProps) if (propName in layerRef) normalizedLayer[propName] = layerRef[propName];
		}
		return normalizedLayer || layer;
	});
	return {
		...style,
		layers
	};
}
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/utils/deep-equal.js
/**
* Compare two points
* @param a
* @param b
* @returns true if the points are equal
*/
function arePointsEqual(a, b) {
	const ax = Array.isArray(a) ? a[0] : a ? a.x : 0;
	const ay = Array.isArray(a) ? a[1] : a ? a.y : 0;
	const bx = Array.isArray(b) ? b[0] : b ? b.x : 0;
	const by = Array.isArray(b) ? b[1] : b ? b.y : 0;
	return ax === bx && ay === by;
}
/**
* Compare any two objects
* @param a
* @param b
* @returns true if the objects are deep equal
*/
function deepEqual(a, b) {
	if (a === b) return true;
	if (!a || !b) return false;
	if (Array.isArray(a)) {
		if (!Array.isArray(b) || a.length !== b.length) return false;
		for (let i = 0; i < a.length; i++) if (!deepEqual(a[i], b[i])) return false;
		return true;
	} else if (Array.isArray(b)) return false;
	if (typeof a === "object" && typeof b === "object") {
		const aKeys = Object.keys(a);
		const bKeys = Object.keys(b);
		if (aKeys.length !== bKeys.length) return false;
		for (const key of aKeys) {
			if (!b.hasOwnProperty(key)) return false;
			if (!deepEqual(a[key], b[key])) return false;
		}
		return true;
	}
	return false;
}
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/mapbox/mapbox.js
var DEFAULT_STYLE = {
	version: 8,
	sources: {},
	layers: []
};
var DEFAULT_SETTINGS = {
	minZoom: 0,
	maxZoom: 22,
	minPitch: 0,
	maxPitch: 85,
	maxBounds: [
		-180,
		-85.051129,
		180,
		85.051129
	],
	projection: "mercator",
	renderWorldCopies: true
};
var pointerEvents = {
	mousedown: "onMouseDown",
	mouseup: "onMouseUp",
	mouseover: "onMouseOver",
	mousemove: "onMouseMove",
	click: "onClick",
	dblclick: "onDblClick",
	mouseenter: "onMouseEnter",
	mouseleave: "onMouseLeave",
	mouseout: "onMouseOut",
	contextmenu: "onContextMenu",
	touchstart: "onTouchStart",
	touchend: "onTouchEnd",
	touchmove: "onTouchMove",
	touchcancel: "onTouchCancel"
};
var cameraEvents = {
	movestart: "onMoveStart",
	move: "onMove",
	moveend: "onMoveEnd",
	dragstart: "onDragStart",
	drag: "onDrag",
	dragend: "onDragEnd",
	zoomstart: "onZoomStart",
	zoom: "onZoom",
	zoomend: "onZoomEnd",
	rotatestart: "onRotateStart",
	rotate: "onRotate",
	rotateend: "onRotateEnd",
	pitchstart: "onPitchStart",
	pitch: "onPitch",
	pitchend: "onPitchEnd"
};
var otherEvents = {
	wheel: "onWheel",
	boxzoomstart: "onBoxZoomStart",
	boxzoomend: "onBoxZoomEnd",
	boxzoomcancel: "onBoxZoomCancel",
	resize: "onResize",
	load: "onLoad",
	render: "onRender",
	idle: "onIdle",
	remove: "onRemove",
	data: "onData",
	styledata: "onStyleData",
	sourcedata: "onSourceData",
	error: "onError"
};
var settingNames = [
	"minZoom",
	"maxZoom",
	"minPitch",
	"maxPitch",
	"maxBounds",
	"projection",
	"renderWorldCopies"
];
var handlerNames = [
	"scrollZoom",
	"boxZoom",
	"dragRotate",
	"dragPan",
	"keyboard",
	"doubleClickZoom",
	"touchZoomRotate",
	"touchPitch"
];
/**
* A wrapper for mapbox-gl's Map class
*/
var Mapbox = class Mapbox {
	constructor(MapClass, props, container) {
		/** mapboxgl.Map instance */
		this._map = null;
		/** Making updates driven by React props. Do not trigger React callbacks to avoid infinite loop */
		this._internalUpdate = false;
		/** Map is currently rendering */
		this._inRender = false;
		/** Map features under the pointer */
		this._hoveredFeatures = null;
		/** View state changes driven by React props
		* They still need to fire move/etc. events because controls such as marker/popup
		* subscribe to the move event internally to update their position
		* React callbacks like onMove are not called for these */
		this._deferredEvents = {
			move: false,
			zoom: false,
			pitch: false,
			rotate: false
		};
		this._onEvent = (e) => {
			const cb = this.props[otherEvents[e.type]];
			if (cb) cb(e);
			else if (e.type === "error") console.error(e.error);
		};
		this._onPointerEvent = (e) => {
			if (e.type === "mousemove" || e.type === "mouseout") this._updateHover(e);
			const cb = this.props[pointerEvents[e.type]];
			if (cb) {
				if (this.props.interactiveLayerIds && e.type !== "mouseover" && e.type !== "mouseout") e.features = this._hoveredFeatures || this._queryRenderedFeatures(e.point);
				cb(e);
				delete e.features;
			}
		};
		this._onCameraEvent = (e) => {
			if (!this._internalUpdate) {
				const cb = this.props[cameraEvents[e.type]];
				const tr = this._proxyTransform;
				if (cb) {
					e.viewState = transformToViewState(tr.$proposedTransform ?? tr);
					cb(e);
				}
				if (e.type === "moveend") tr.$proposedTransform = null;
			}
			if (e.type in this._deferredEvents) this._deferredEvents[e.type] = false;
		};
		this._MapClass = MapClass;
		this.props = props;
		this._initialize(container);
	}
	get map() {
		return this._map;
	}
	get transform() {
		return this._map.transform;
	}
	setProps(props) {
		const oldProps = this.props;
		this.props = props;
		const settingsChanged = this._updateSettings(props, oldProps);
		const sizeChanged = this._updateSize(props);
		const viewStateChanged = this._updateViewState(props, true);
		this._updateStyle(props, oldProps);
		this._updateStyleComponents(props, oldProps);
		this._updateHandlers(props, oldProps);
		if (settingsChanged || sizeChanged || viewStateChanged && !this._map.isMoving()) this.redraw();
	}
	static reuse(props, container) {
		const that = Mapbox.savedMaps.pop();
		if (!that) return null;
		const map = that.map;
		const oldContainer = map.getContainer();
		container.className = oldContainer.className;
		while (oldContainer.childNodes.length > 0) container.appendChild(oldContainer.childNodes[0]);
		map._container = container;
		that.setProps({
			...props,
			styleDiffing: false
		});
		map.resize();
		const { initialViewState } = props;
		if (initialViewState) if (initialViewState.bounds) map.fitBounds(initialViewState.bounds, {
			...initialViewState.fitBoundsOptions,
			duration: 0
		});
		else that._updateViewState(initialViewState, false);
		if (map.isStyleLoaded()) map.fire("load");
		else map.once("styledata", () => map.fire("load"));
		map._update();
		return that;
	}
	_initialize(container) {
		const { props } = this;
		const { mapStyle = DEFAULT_STYLE } = props;
		const mapOptions = {
			...props,
			...props.initialViewState,
			accessToken: props.mapboxAccessToken || getAccessTokenFromEnv() || null,
			container,
			style: normalizeStyle(mapStyle)
		};
		const viewState = mapOptions.initialViewState || mapOptions.viewState || mapOptions;
		Object.assign(mapOptions, {
			center: [viewState.longitude || 0, viewState.latitude || 0],
			zoom: viewState.zoom || 0,
			pitch: viewState.pitch || 0,
			bearing: viewState.bearing || 0
		});
		if (props.gl) {
			const getContext = HTMLCanvasElement.prototype.getContext;
			HTMLCanvasElement.prototype.getContext = () => {
				HTMLCanvasElement.prototype.getContext = getContext;
				return props.gl;
			};
		}
		const map = new this._MapClass(mapOptions);
		if (viewState.padding) map.setPadding(viewState.padding);
		if (props.cursor) map.getCanvas().style.cursor = props.cursor;
		this._createProxyTransform(map);
		const renderMap = map._render;
		map._render = (arg) => {
			this._inRender = true;
			renderMap.call(map, arg);
			this._inRender = false;
		};
		const runRenderTaskQueue = map._renderTaskQueue.run;
		map._renderTaskQueue.run = (arg) => {
			this._proxyTransform.$internalUpdate = true;
			runRenderTaskQueue.call(map._renderTaskQueue, arg);
			this._proxyTransform.$internalUpdate = false;
			this._fireDefferedEvents();
		};
		const jumpTo = map.jumpTo;
		map.jumpTo = (...args) => {
			this._proxyTransform.$internalUpdate = true;
			jumpTo.apply(map, args);
			this._proxyTransform.$internalUpdate = false;
			return map;
		};
		const fireEvent = map.fire;
		map.fire = this._fireEvent.bind(this, fireEvent);
		map.on("styledata", () => {
			this._updateStyleComponents(this.props, {});
		});
		map.on("sourcedata", () => {
			this._updateStyleComponents(this.props, {});
		});
		for (const eventName in pointerEvents) map.on(eventName, this._onPointerEvent);
		for (const eventName in cameraEvents) map.on(eventName, this._onCameraEvent);
		for (const eventName in otherEvents) map.on(eventName, this._onEvent);
		this._map = map;
	}
	recycle() {
		this.map.getContainer().querySelector("[mapboxgl-children]")?.remove();
		Mapbox.savedMaps.push(this);
	}
	destroy() {
		this._map.remove();
	}
	redraw() {
		const map = this._map;
		if (!this._inRender && map.style) {
			if (map._frame) {
				map._frame.cancel();
				map._frame = null;
			}
			map._render();
		}
	}
	_createProxyTransform(map) {
		const proxyTransform = createProxyTransform(map.transform);
		map.transform = proxyTransform;
		map.painter.transform = proxyTransform;
		this._proxyTransform = proxyTransform;
	}
	_updateSize(nextProps) {
		const { viewState } = nextProps;
		if (viewState) {
			const map = this._map;
			if (viewState.width !== map.transform.width || viewState.height !== map.transform.height) {
				map.resize();
				return true;
			}
		}
		return false;
	}
	_updateViewState(nextProps, triggerEvents) {
		const viewState = nextProps.viewState || nextProps;
		const tr = this._proxyTransform;
		const { zoom, pitch, bearing } = tr;
		const changed = compareViewStateWithTransform(this._proxyTransform, viewState);
		tr.$reactViewState = viewState;
		if (changed && triggerEvents) {
			const deferredEvents = this._deferredEvents;
			deferredEvents.move = true;
			deferredEvents.zoom || (deferredEvents.zoom = zoom !== tr.zoom);
			deferredEvents.rotate || (deferredEvents.rotate = bearing !== tr.bearing);
			deferredEvents.pitch || (deferredEvents.pitch = pitch !== tr.pitch);
		}
		return changed;
	}
	_updateSettings(nextProps, currProps) {
		const map = this._map;
		let changed = false;
		for (const propName of settingNames) if ((propName in nextProps || propName in currProps) && !deepEqual(nextProps[propName], currProps[propName])) {
			changed = true;
			const nextValue = propName in nextProps ? nextProps[propName] : DEFAULT_SETTINGS[propName];
			map[`set${propName[0].toUpperCase()}${propName.slice(1)}`]?.call(map, nextValue);
		}
		return changed;
	}
	_updateStyle(nextProps, currProps) {
		if (nextProps.cursor !== currProps.cursor) this._map.getCanvas().style.cursor = nextProps.cursor || "";
		if (nextProps.mapStyle !== currProps.mapStyle) {
			const { mapStyle = DEFAULT_STYLE, styleDiffing = true } = nextProps;
			const options = { diff: styleDiffing };
			if ("localIdeographFontFamily" in nextProps) options.localIdeographFontFamily = nextProps.localIdeographFontFamily;
			this._map.setStyle(normalizeStyle(mapStyle), options);
			return true;
		}
		return false;
	}
	_updateStyleComponents(nextProps, currProps) {
		const map = this._map;
		let changed = false;
		if (map.isStyleLoaded()) {
			if ("light" in nextProps && map.setLight && !deepEqual(nextProps.light, currProps.light)) {
				changed = true;
				map.setLight(nextProps.light);
			}
			if ("fog" in nextProps && map.setFog && !deepEqual(nextProps.fog, currProps.fog)) {
				changed = true;
				map.setFog(nextProps.fog);
			}
			if ("terrain" in nextProps && map.setTerrain && !deepEqual(nextProps.terrain, currProps.terrain)) {
				if (!nextProps.terrain || map.getSource(nextProps.terrain.source)) {
					changed = true;
					map.setTerrain(nextProps.terrain);
				}
			}
		}
		return changed;
	}
	_updateHandlers(nextProps, currProps) {
		const map = this._map;
		let changed = false;
		for (const propName of handlerNames) {
			const newValue = nextProps[propName] ?? true;
			if (!deepEqual(newValue, currProps[propName] ?? true)) {
				changed = true;
				if (newValue) map[propName].enable(newValue);
				else map[propName].disable();
			}
		}
		return changed;
	}
	_queryRenderedFeatures(point) {
		const map = this._map;
		const { interactiveLayerIds = [] } = this.props;
		try {
			return map.queryRenderedFeatures(point, { layers: interactiveLayerIds.filter(map.getLayer.bind(map)) });
		} catch {
			return [];
		}
	}
	_updateHover(e) {
		const { props } = this;
		if (props.interactiveLayerIds && (props.onMouseMove || props.onMouseEnter || props.onMouseLeave)) {
			const eventType = e.type;
			const wasHovering = this._hoveredFeatures?.length > 0;
			const features = this._queryRenderedFeatures(e.point);
			const isHovering = features.length > 0;
			if (!isHovering && wasHovering) {
				e.type = "mouseleave";
				this._onPointerEvent(e);
			}
			this._hoveredFeatures = features;
			if (isHovering && !wasHovering) {
				e.type = "mouseenter";
				this._onPointerEvent(e);
			}
			e.type = eventType;
		} else this._hoveredFeatures = null;
	}
	_fireEvent(baseFire, event, properties) {
		const map = this._map;
		const tr = this._proxyTransform;
		const internal = tr.$internalUpdate;
		try {
			tr.$internalUpdate = false;
			baseFire.call(map, event, properties);
		} finally {
			tr.$internalUpdate = internal;
		}
		return map;
	}
	_fireDefferedEvents() {
		const map = this._map;
		this._internalUpdate = true;
		for (const eventType in this._deferredEvents) if (this._deferredEvents[eventType]) map.fire(eventType);
		this._internalUpdate = false;
	}
};
Mapbox.savedMaps = [];
/**
* Access token can be provided via one of:
*   mapboxAccessToken prop
*   access_token query parameter
*   MapboxAccessToken environment variable
*   REACT_APP_MAPBOX_ACCESS_TOKEN environment variable
* @returns access token
*/
function getAccessTokenFromEnv() {
	let accessToken = null;
	if (typeof location !== "undefined") {
		const match = /access_token=([^&\/]*)/.exec(location.search);
		accessToken = match && match[1];
	}
	try {
		accessToken = accessToken || process.env.MapboxAccessToken;
	} catch {}
	try {
		accessToken = accessToken || process.env.REACT_APP_MAPBOX_ACCESS_TOKEN;
	} catch {}
	return accessToken;
}
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/mapbox/create-ref.js
/** These methods may break the react binding if called directly */
var skipMethods = [
	"setMaxBounds",
	"setMinZoom",
	"setMaxZoom",
	"setMinPitch",
	"setMaxPitch",
	"setRenderWorldCopies",
	"setProjection",
	"setStyle",
	"addSource",
	"removeSource",
	"addLayer",
	"removeLayer",
	"setLayerZoomRange",
	"setFilter",
	"setPaintProperty",
	"setLayoutProperty",
	"setLight",
	"setTerrain",
	"setFog",
	"remove"
];
function createRef(mapInstance) {
	if (!mapInstance) return null;
	const map = mapInstance.map;
	const ref = {
		getMap: () => map,
		getCenter: () => mapInstance.transform.center,
		getZoom: () => mapInstance.transform.zoom,
		getBearing: () => mapInstance.transform.bearing,
		getPitch: () => mapInstance.transform.pitch,
		getPadding: () => mapInstance.transform.padding,
		getBounds: () => mapInstance.transform.getBounds(),
		project: (lnglat) => {
			const tr = map.transform;
			map.transform = mapInstance.transform;
			const result = map.project(lnglat);
			map.transform = tr;
			return result;
		},
		unproject: (point) => {
			const tr = map.transform;
			map.transform = mapInstance.transform;
			const result = map.unproject(point);
			map.transform = tr;
			return result;
		},
		queryTerrainElevation: (lnglat, options) => {
			const tr = map.transform;
			map.transform = mapInstance.transform;
			const result = map.queryTerrainElevation(lnglat, options);
			map.transform = tr;
			return result;
		},
		queryRenderedFeatures: (geometry, options) => {
			const tr = map.transform;
			map.transform = mapInstance.transform;
			const result = map.queryRenderedFeatures(geometry, options);
			map.transform = tr;
			return result;
		}
	};
	for (const key of getMethodNames(map)) if (!(key in ref) && !skipMethods.includes(key)) ref[key] = map[key].bind(map);
	return ref;
}
function getMethodNames(obj) {
	const result = /* @__PURE__ */ new Set();
	let proto = obj;
	while (proto) {
		for (const key of Object.getOwnPropertyNames(proto)) if (key[0] !== "_" && typeof obj[key] === "function" && key !== "fire" && key !== "setEventedParent") result.add(key);
		proto = Object.getPrototypeOf(proto);
	}
	return Array.from(result);
}
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/utils/use-isomorphic-layout-effect.js
var useIsomorphicLayoutEffect = typeof document !== "undefined" ? import_react.useLayoutEffect : import_react.useEffect;
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/utils/set-globals.js
var globalSettings = [
	"baseApiUrl",
	"maxParallelImageRequests",
	"workerClass",
	"workerCount",
	"workerUrl"
];
function setGlobals(mapLib, props) {
	for (const key of globalSettings) if (key in props) mapLib[key] = props[key];
	const { RTLTextPlugin = "https://api.mapbox.com/mapbox-gl-js/plugins/mapbox-gl-rtl-text/v0.2.3/mapbox-gl-rtl-text.js" } = props;
	if (RTLTextPlugin && mapLib.getRTLTextPluginStatus && mapLib.getRTLTextPluginStatus() === "unavailable") mapLib.setRTLTextPlugin(RTLTextPlugin, (error) => {
		if (error) console.error(error);
	}, true);
}
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/components/map.js
var MapContext = import_react.createContext(null);
function _Map(props, ref) {
	const mountedMapsContext = (0, import_react.useContext)(MountedMapsContext);
	const [mapInstance, setMapInstance] = (0, import_react.useState)(null);
	const containerRef = (0, import_react.useRef)();
	const { current: contextValue } = (0, import_react.useRef)({
		mapLib: null,
		map: null
	});
	(0, import_react.useEffect)(() => {
		const mapLib = props.mapLib;
		let isMounted = true;
		let mapbox;
		Promise.resolve(mapLib || import("./mapbox-gl.js").then((m) => /* @__PURE__ */ __toESM(m.default, 1))).then((module) => {
			if (!isMounted) return;
			if (!module) throw new Error("Invalid mapLib");
			const mapboxgl = "Map" in module ? module : module.default;
			if (!mapboxgl.Map) throw new Error("Invalid mapLib");
			setGlobals(mapboxgl, props);
			if (props.reuseMaps) mapbox = Mapbox.reuse(props, containerRef.current);
			if (!mapbox) mapbox = new Mapbox(mapboxgl.Map, props, containerRef.current);
			contextValue.map = createRef(mapbox);
			contextValue.mapLib = mapboxgl;
			setMapInstance(mapbox);
			mountedMapsContext?.onMapMount(contextValue.map, props.id);
		}).catch((error) => {
			const { onError } = props;
			if (onError) onError({
				type: "error",
				target: null,
				error
			});
			else console.error(error);
		});
		return () => {
			isMounted = false;
			if (mapbox) {
				mountedMapsContext?.onMapUnmount(props.id);
				if (props.reuseMaps) mapbox.recycle();
				else mapbox.destroy();
			}
		};
	}, []);
	useIsomorphicLayoutEffect(() => {
		if (mapInstance) mapInstance.setProps(props);
	});
	(0, import_react.useImperativeHandle)(ref, () => contextValue.map, [mapInstance]);
	const style = (0, import_react.useMemo)(() => ({
		position: "relative",
		width: "100%",
		height: "100%",
		...props.style
	}), [props.style]);
	return import_react.createElement("div", {
		id: props.id,
		ref: containerRef,
		style
	}, mapInstance && import_react.createElement(MapContext.Provider, { value: contextValue }, import_react.createElement("div", {
		"mapboxgl-children": "",
		style: { height: "100%" }
	}, props.children)));
}
var Map = import_react.forwardRef(_Map);
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/utils/apply-react-style.js
var import_react_dom = /* @__PURE__ */ __toESM(require_react_dom(), 1);
var unitlessNumber = /box|flex|grid|column|lineHeight|fontWeight|opacity|order|tabSize|zIndex/;
function applyReactStyle(element, styles) {
	if (!element || !styles) return;
	const style = element.style;
	for (const key in styles) {
		const value = styles[key];
		if (Number.isFinite(value) && !unitlessNumber.test(key)) style[key] = `${value}px`;
		else style[key] = value;
	}
}
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/utils/compare-class-names.js
/** Compare two classNames string and return the difference */
function compareClassNames(prevClassName, nextClassName) {
	if (prevClassName === nextClassName) return null;
	const prevClassList = getClassList(prevClassName);
	const nextClassList = getClassList(nextClassName);
	const diff = [];
	for (const c of nextClassList) if (!prevClassList.has(c)) diff.push(c);
	for (const c of prevClassList) if (!nextClassList.has(c)) diff.push(c);
	return diff.length === 0 ? null : diff;
}
function getClassList(className) {
	return new Set(className ? className.trim().split(/\s+/) : []);
}
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/components/marker.js
var Marker = (0, import_react.memo)((0, import_react.forwardRef)((props, ref) => {
	const { map, mapLib } = (0, import_react.useContext)(MapContext);
	const thisRef = (0, import_react.useRef)({ props });
	const marker = (0, import_react.useMemo)(() => {
		let hasChildren = false;
		import_react.Children.forEach(props.children, (el) => {
			if (el) hasChildren = true;
		});
		const options = {
			...props,
			element: hasChildren ? document.createElement("div") : null
		};
		const mk = new mapLib.Marker(options);
		mk.setLngLat([props.longitude, props.latitude]);
		mk.getElement().addEventListener("click", (e) => {
			thisRef.current.props.onClick?.({
				type: "click",
				target: mk,
				originalEvent: e
			});
		});
		mk.on("dragstart", (e) => {
			const evt = e;
			evt.lngLat = marker.getLngLat();
			thisRef.current.props.onDragStart?.(evt);
		});
		mk.on("drag", (e) => {
			const evt = e;
			evt.lngLat = marker.getLngLat();
			thisRef.current.props.onDrag?.(evt);
		});
		mk.on("dragend", (e) => {
			const evt = e;
			evt.lngLat = marker.getLngLat();
			thisRef.current.props.onDragEnd?.(evt);
		});
		return mk;
	}, []);
	(0, import_react.useEffect)(() => {
		marker.addTo(map.getMap());
		return () => {
			marker.remove();
		};
	}, []);
	const { longitude, latitude, offset, style, draggable = false, popup = null, rotation = 0, rotationAlignment = "auto", pitchAlignment = "auto" } = props;
	(0, import_react.useEffect)(() => {
		applyReactStyle(marker.getElement(), style);
	}, [style]);
	(0, import_react.useImperativeHandle)(ref, () => marker, []);
	const oldProps = thisRef.current.props;
	if (marker.getLngLat().lng !== longitude || marker.getLngLat().lat !== latitude) marker.setLngLat([longitude, latitude]);
	if (offset && !arePointsEqual(marker.getOffset(), offset)) marker.setOffset(offset);
	if (marker.isDraggable() !== draggable) marker.setDraggable(draggable);
	if (marker.getRotation() !== rotation) marker.setRotation(rotation);
	if (marker.getRotationAlignment() !== rotationAlignment) marker.setRotationAlignment(rotationAlignment);
	if (marker.getPitchAlignment() !== pitchAlignment) marker.setPitchAlignment(pitchAlignment);
	if (marker.getPopup() !== popup) marker.setPopup(popup);
	const classNameDiff = compareClassNames(oldProps.className, props.className);
	if (classNameDiff) for (const c of classNameDiff) marker.toggleClassName(c);
	thisRef.current.props = props;
	return (0, import_react_dom.createPortal)(props.children, marker.getElement());
}));
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/components/popup.js
var Popup = (0, import_react.memo)((0, import_react.forwardRef)((props, ref) => {
	const { map, mapLib } = (0, import_react.useContext)(MapContext);
	const container = (0, import_react.useMemo)(() => {
		return document.createElement("div");
	}, []);
	const thisRef = (0, import_react.useRef)({ props });
	const popup = (0, import_react.useMemo)(() => {
		const options = { ...props };
		const pp = new mapLib.Popup(options);
		pp.setLngLat([props.longitude, props.latitude]);
		pp.once("open", (e) => {
			thisRef.current.props.onOpen?.(e);
		});
		return pp;
	}, []);
	(0, import_react.useEffect)(() => {
		const onClose = (e) => {
			thisRef.current.props.onClose?.(e);
		};
		popup.on("close", onClose);
		popup.setDOMContent(container).addTo(map.getMap());
		return () => {
			popup.off("close", onClose);
			if (popup.isOpen()) popup.remove();
		};
	}, []);
	(0, import_react.useEffect)(() => {
		applyReactStyle(popup.getElement(), props.style);
	}, [props.style]);
	(0, import_react.useImperativeHandle)(ref, () => popup, []);
	if (popup.isOpen()) {
		const oldProps = thisRef.current.props;
		if (popup.getLngLat().lng !== props.longitude || popup.getLngLat().lat !== props.latitude) popup.setLngLat([props.longitude, props.latitude]);
		if (props.offset && !deepEqual(oldProps.offset, props.offset)) {
			popup.options.anchor = props.anchor;
			popup.setOffset(props.offset);
		}
		if (oldProps.anchor !== props.anchor || oldProps.maxWidth !== props.maxWidth) popup.setMaxWidth(props.maxWidth);
		const classNameDiff = compareClassNames(oldProps.className, props.className);
		if (classNameDiff) for (const c of classNameDiff) popup.toggleClassName(c);
		thisRef.current.props = props;
	}
	return (0, import_react_dom.createPortal)(props.children, container);
}));
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/components/use-control.js
function useControl(onCreate, arg1, arg2, arg3) {
	const context = (0, import_react.useContext)(MapContext);
	const ctrl = (0, import_react.useMemo)(() => onCreate(context), []);
	(0, import_react.useEffect)(() => {
		const opts = arg3 || arg2 || arg1;
		const onAdd = typeof arg1 === "function" && typeof arg2 === "function" ? arg1 : null;
		const onRemove = typeof arg2 === "function" ? arg2 : typeof arg1 === "function" ? arg1 : null;
		const { map } = context;
		if (!map.hasControl(ctrl)) {
			map.addControl(ctrl, opts?.position);
			if (onAdd) onAdd(context);
		}
		return () => {
			if (onRemove) onRemove(context);
			if (map.hasControl(ctrl)) map.removeControl(ctrl);
		};
	}, []);
	return ctrl;
}
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/components/attribution-control.js
function _AttributionControl(props) {
	const ctrl = useControl(({ mapLib }) => new mapLib.AttributionControl(props), { position: props.position });
	(0, import_react.useEffect)(() => {
		applyReactStyle(ctrl._container, props.style);
	}, [props.style]);
	return null;
}
var AttributionControl = (0, import_react.memo)(_AttributionControl);
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/components/fullscreen-control.js
function _FullscreenControl(props) {
	const ctrl = useControl(({ mapLib }) => new mapLib.FullscreenControl({ container: props.containerId && document.getElementById(props.containerId) }), { position: props.position });
	(0, import_react.useEffect)(() => {
		applyReactStyle(ctrl._controlContainer, props.style);
	}, [props.style]);
	return null;
}
var FullscreenControl = (0, import_react.memo)(_FullscreenControl);
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/components/geolocate-control.js
function _GeolocateControl(props, ref) {
	const thisRef = (0, import_react.useRef)({ props });
	const ctrl = useControl(({ mapLib }) => {
		const gc = new mapLib.GeolocateControl(props);
		const setupUI = gc._setupUI.bind(gc);
		gc._setupUI = (args) => {
			if (!gc._container.hasChildNodes()) setupUI(args);
		};
		gc.on("geolocate", (e) => {
			thisRef.current.props.onGeolocate?.(e);
		});
		gc.on("error", (e) => {
			thisRef.current.props.onError?.(e);
		});
		gc.on("outofmaxbounds", (e) => {
			thisRef.current.props.onOutOfMaxBounds?.(e);
		});
		gc.on("trackuserlocationstart", (e) => {
			thisRef.current.props.onTrackUserLocationStart?.(e);
		});
		gc.on("trackuserlocationend", (e) => {
			thisRef.current.props.onTrackUserLocationEnd?.(e);
		});
		return gc;
	}, { position: props.position });
	thisRef.current.props = props;
	(0, import_react.useImperativeHandle)(ref, () => ctrl, []);
	(0, import_react.useEffect)(() => {
		applyReactStyle(ctrl._container, props.style);
	}, [props.style]);
	return null;
}
var GeolocateControl = (0, import_react.memo)((0, import_react.forwardRef)(_GeolocateControl));
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/components/navigation-control.js
function _NavigationControl(props) {
	const ctrl = useControl(({ mapLib }) => new mapLib.NavigationControl(props), { position: props.position });
	(0, import_react.useEffect)(() => {
		applyReactStyle(ctrl._container, props.style);
	}, [props.style]);
	return null;
}
var NavigationControl = (0, import_react.memo)(_NavigationControl);
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/components/scale-control.js
function _ScaleControl(props) {
	const ctrl = useControl(({ mapLib }) => new mapLib.ScaleControl(props), { position: props.position });
	const propsRef = (0, import_react.useRef)(props);
	const prevProps = propsRef.current;
	propsRef.current = props;
	const { style } = props;
	if (props.maxWidth !== void 0 && props.maxWidth !== prevProps.maxWidth) ctrl.options.maxWidth = props.maxWidth;
	if (props.unit !== void 0 && props.unit !== prevProps.unit) ctrl.setUnit(props.unit);
	(0, import_react.useEffect)(() => {
		applyReactStyle(ctrl._container, style);
	}, [style]);
	return null;
}
var ScaleControl = (0, import_react.memo)(_ScaleControl);
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/utils/assert.js
function assert(condition, message) {
	if (!condition) throw new Error(message);
}
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/components/source.js
var sourceCounter = 0;
function createSource(map, id, props) {
	if (map.style && map.style._loaded) {
		const options = { ...props };
		delete options.id;
		delete options.children;
		map.addSource(id, options);
		return map.getSource(id);
	}
	return null;
}
function updateSource(source, props, prevProps) {
	assert(props.id === prevProps.id, "source id changed");
	assert(props.type === prevProps.type, "source type changed");
	let changedKey = "";
	let changedKeyCount = 0;
	for (const key in props) if (key !== "children" && key !== "id" && !deepEqual(prevProps[key], props[key])) {
		changedKey = key;
		changedKeyCount++;
	}
	if (!changedKeyCount) return;
	const type = props.type;
	if (type === "geojson") source.setData(props.data);
	else if (type === "image") source.updateImage({
		url: props.url,
		coordinates: props.coordinates
	});
	else if ("setCoordinates" in source && changedKeyCount === 1 && changedKey === "coordinates") source.setCoordinates(props.coordinates);
	else if ("setUrl" in source && changedKey === "url") source.setUrl(props.url);
	else if ("setTiles" in source && changedKey === "tiles") source.setTiles(props.tiles);
	else console.warn(`Unable to update <Source> prop: ${changedKey}`);
}
function Source(props) {
	const map = (0, import_react.useContext)(MapContext).map.getMap();
	const propsRef = (0, import_react.useRef)(props);
	const [, setStyleLoaded] = (0, import_react.useState)(0);
	const id = (0, import_react.useMemo)(() => props.id || `jsx-source-${sourceCounter++}`, []);
	(0, import_react.useEffect)(() => {
		if (map) {
			const forceUpdate = () => setTimeout(() => setStyleLoaded((version) => version + 1), 0);
			map.on("styledata", forceUpdate);
			forceUpdate();
			return () => {
				map.off("styledata", forceUpdate);
				if (map.style && map.style._loaded && map.getSource(id)) {
					const allLayers = map.getStyle()?.layers;
					if (allLayers) {
						for (const layer of allLayers) if (layer.source === id) map.removeLayer(layer.id);
					}
					map.removeSource(id);
				}
			};
		}
	}, [map]);
	let source = map && map.style && map.getSource(id);
	if (source) updateSource(source, props, propsRef.current);
	else source = createSource(map, id, props);
	propsRef.current = props;
	return source && import_react.Children.map(props.children, (child) => child && (0, import_react.cloneElement)(child, { source: id })) || null;
}
//#endregion
//#region node_modules/@vis.gl/react-mapbox/dist/components/layer.js
function updateLayer(map, id, props, prevProps) {
	assert(props.id === prevProps.id, "layer id changed");
	assert(props.type === prevProps.type, "layer type changed");
	if (props.type === "custom" || prevProps.type === "custom") return;
	const { layout = {}, paint = {}, filter, minzoom, maxzoom, beforeId } = props;
	if (beforeId !== prevProps.beforeId) map.moveLayer(id, beforeId);
	if (layout !== prevProps.layout) {
		const prevLayout = prevProps.layout || {};
		for (const key in layout) if (!deepEqual(layout[key], prevLayout[key])) map.setLayoutProperty(id, key, layout[key]);
		for (const key in prevLayout) if (!layout.hasOwnProperty(key)) map.setLayoutProperty(id, key, void 0);
	}
	if (paint !== prevProps.paint) {
		const prevPaint = prevProps.paint || {};
		for (const key in paint) if (!deepEqual(paint[key], prevPaint[key])) map.setPaintProperty(id, key, paint[key]);
		for (const key in prevPaint) if (!paint.hasOwnProperty(key)) map.setPaintProperty(id, key, void 0);
	}
	if (!deepEqual(filter, prevProps.filter)) map.setFilter(id, filter);
	if (minzoom !== prevProps.minzoom || maxzoom !== prevProps.maxzoom) map.setLayerZoomRange(id, minzoom, maxzoom);
}
function createLayer(map, id, props) {
	if (map.style && map.style._loaded && (!("source" in props) || map.getSource(props.source))) {
		const options = {
			...props,
			id
		};
		delete options.beforeId;
		map.addLayer(options, props.beforeId);
	}
}
var layerCounter = 0;
function Layer(props) {
	const map = (0, import_react.useContext)(MapContext).map.getMap();
	const propsRef = (0, import_react.useRef)(props);
	const [, setStyleLoaded] = (0, import_react.useState)(0);
	const id = (0, import_react.useMemo)(() => props.id || `jsx-layer-${layerCounter++}`, []);
	(0, import_react.useEffect)(() => {
		if (map) {
			const forceUpdate = () => setStyleLoaded((version) => version + 1);
			map.on("styledata", forceUpdate);
			forceUpdate();
			return () => {
				map.off("styledata", forceUpdate);
				if (map.style && map.style._loaded && map.getLayer(id)) map.removeLayer(id);
			};
		}
	}, [map]);
	if (map && map.style && map.getLayer(id)) try {
		updateLayer(map, id, props, propsRef.current);
	} catch (error) {
		console.warn(error);
	}
	else createLayer(map, id, props);
	propsRef.current = props;
	return null;
}
//#endregion
export { AttributionControl, FullscreenControl, GeolocateControl, Layer, Map, Map as default, MapProvider, Marker, NavigationControl, Popup, ScaleControl, Source, useControl, useMap };

//# sourceMappingURL=react-map-gl_mapbox.js.map