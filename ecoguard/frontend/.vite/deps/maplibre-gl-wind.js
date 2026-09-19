import { $ as isExternalImage, C as toDoublePrecisionArray, Ct as defaultLogger, D as addMetersToLngLat, F as project32_default, J as Sampler, K as color_default, L as getOffsetOrigin, P as worldToPixels, Q as getExternalImageSize, T as picking_default, U as UNIT, _ as LIFECYCLE, at as uid$1, bt as getShaderModuleDependencies, c as Transition, f as ASYNC_DEFAULTS_SYMBOL, g as DEPRECATED_PROPS_SYMBOL, h as COMPONENT_SYMBOL, ht as sub, it as Resource, l as deepEqual$1, m as ASYNC_RESOLVED_SYMBOL, nt as dataTypeDecoder, ot as log, p as ASYNC_ORIGINAL_SYMBOL, q as Texture, rt as Buffer, s as assert, tt as vertexFormatDecoder, u as fillArray, ut as transformMat4, v as PROP_TYPES_SYMBOL, vt as lerp, w as typed_array_manager_default, wt as load, x as mergeBounds, xt as debug, y as WebMercatorViewport, yt as ShaderAssembler, z as memoize } from "./webgl-developer-tools-CC6tnIIX.js";
import { a as getTypedArrayConstructor, c as resolveVariableShaderTypeAlias, d as Shader, f as TextureView, i as alignTo, l as normalizeBindingsByGroup, o as getAttributeInfosFromLayouts, r as getScratchArrayBuffer, s as getVariableShaderTypeInfo, t as WebGLDevice, u as RenderPipeline } from "./webgl-device-DmZ5B3dw.js";
//#region node_modules/@math.gl/types/dist/is-array.js
/**
* Check is an array is a typed array
* @param value value to be tested
* @returns input with type narrowed to TypedArray, or null
*/
function isTypedArray$1(value) {
	return ArrayBuffer.isView(value) && !(value instanceof DataView);
}
/**
* Check is an array is an array of numbers)
* @param value value to be tested
* @returns input with type narrowed to NumberArray, or null
*/
function isNumberArray$1(value) {
	if (Array.isArray(value)) return value.length === 0 || typeof value[0] === "number";
	return false;
}
/**
* Check is an array is a numeric array (typed array or array of numbers)
* @param value value to be tested
* @returns input with type narrowed to NumericArray, or null
*/
function isNumericArray(value) {
	return isTypedArray$1(value) || isNumberArray$1(value);
}
//#endregion
//#region node_modules/@luma.gl/shadertools/dist/lib/glsl-utils/shader-utils.js
var FS300 = `#version 300 es\nout vec4 transform_output;
void main() {
  transform_output = vec4(0);
}`;
/**
* Given the shader input and output variable names,
* builds and return a pass through fragment shader.
*/
function getPassthroughFS(options) {
	const { input, inputChannels, output } = options || {};
	if (!input) return FS300;
	if (!inputChannels) throw new Error("inputChannels");
	return `\
#version 300 es
in ${channelCountToType(inputChannels)} ${input};
out vec4 ${output};
void main() {
  ${output} = ${convertToVec4(input, inputChannels)};
}`;
}
function channelCountToType(channels) {
	switch (channels) {
		case 1: return "float";
		case 2: return "vec2";
		case 3: return "vec3";
		case 4: return "vec4";
		default: throw new Error(`invalid channels: ${channels}`);
	}
}
/** Returns glsl instruction for converting to vec4 */
function convertToVec4(variable, channels) {
	switch (channels) {
		case 1: return `vec4(${variable}, 0.0, 0.0, 1.0)`;
		case 2: return `vec4(${variable}, 0.0, 1.0)`;
		case 3: return `vec4(${variable}, 1.0)`;
		case 4: return variable;
		default: throw new Error(`invalid channels: ${channels}`);
	}
}
//#endregion
//#region node_modules/@luma.gl/shadertools/dist/modules/math/fp64/fp64-utils.js
/**
* Calculate WebGL 64 bit float
* @param a  - the input float number
* @param out - the output array. If not supplied, a new array is created.
* @param startIndex - the index in the output array to fill from. Default 0.
* @returns - the fp64 representation of the input number
*/
function fp64ify(a, out = [], startIndex = 0) {
	const hiPart = Math.fround(a);
	const loPart = a - hiPart;
	out[startIndex] = hiPart;
	out[startIndex + 1] = loPart;
	return out;
}
/**
* Calculate the low part of a WebGL 64 bit float
* @param a the input float number
* @returns the lower 32 bit of the number
*/
function fp64LowPart(a) {
	return a - Math.fround(a);
}
/**
* Calculate WebGL 64 bit matrix (transposed "Float64Array")
* @param matrix  the input matrix
* @returns the fp64 representation of the input matrix
*/
function fp64ifyMatrix4(matrix) {
	const matrixFP64 = new Float32Array(32);
	for (let i = 0; i < 4; ++i) for (let j = 0; j < 4; ++j) {
		const index = i * 4 + j;
		fp64ify(matrix[j * 4 + i], matrixFP64, index * 2);
	}
	return matrixFP64;
}
//#endregion
//#region node_modules/@luma.gl/shadertools/dist/modules/math/fp64/fp64-arithmetic-glsl.js
var fp64arithmeticShader = `\

layout(std140) uniform fp64arithmeticUniforms {
  uniform float ONE;
  uniform float SPLIT;
} fp64;

/*
About LUMA_FP64_CODE_ELIMINATION_WORKAROUND

The purpose of this workaround is to prevent shader compilers from
optimizing away necessary arithmetic operations by swapping their sequences
or transform the equation to some 'equivalent' form.

These helpers implement Dekker/Veltkamp-style error tracking. If the compiler
folds constants or reassociates the arithmetic, the high/low split can stop
tracking the rounding error correctly. That failure mode tends to look fine in
simple coordinate setup, but then breaks down inside iterative arithmetic such
as fp64 Mandelbrot loops.

The method is to multiply an artifical variable, ONE, which will be known to
the compiler to be 1 only at runtime. The whole expression is then represented
as a polynomial with respective to ONE. In the coefficients of all terms, only one a
and one b should appear

err = (a + b) * ONE^6 - a * ONE^5 - (a + b) * ONE^4 + a * ONE^3 - b - (a + b) * ONE^2 + a * ONE
*/

float prevent_fp64_optimization(float value) {
#if defined(LUMA_FP64_CODE_ELIMINATION_WORKAROUND)
  return value + fp64.ONE * 0.0;
#else
  return value;
#endif
}

// Divide float number to high and low floats to extend fraction bits
vec2 split(float a) {
  // Keep SPLIT as a runtime uniform so the compiler cannot fold the Dekker
  // split into a constant expression and reassociate the recovery steps.
  float split = prevent_fp64_optimization(fp64.SPLIT);
  float t = prevent_fp64_optimization(a * split);
  float temp = t - a;
  float a_hi = t - temp;
  float a_lo = a - a_hi;
  return vec2(a_hi, a_lo);
}

// Divide float number again when high float uses too many fraction bits
vec2 split2(vec2 a) {
  vec2 b = split(a.x);
  b.y += a.y;
  return b;
}

// Special sum operation when a > b
vec2 quickTwoSum(float a, float b) {
#if defined(LUMA_FP64_CODE_ELIMINATION_WORKAROUND)
  float sum = (a + b) * fp64.ONE;
  float err = b - (sum - a) * fp64.ONE;
#else
  float sum = a + b;
  float err = b - (sum - a);
#endif
  return vec2(sum, err);
}

// General sum operation
vec2 twoSum(float a, float b) {
  float s = (a + b);
#if defined(LUMA_FP64_CODE_ELIMINATION_WORKAROUND)
  float v = (s * fp64.ONE - a) * fp64.ONE;
  float err = (a - (s - v) * fp64.ONE) * fp64.ONE * fp64.ONE * fp64.ONE + (b - v);
#else
  float v = s - a;
  float err = (a - (s - v)) + (b - v);
#endif
  return vec2(s, err);
}

vec2 twoSub(float a, float b) {
  float s = (a - b);
#if defined(LUMA_FP64_CODE_ELIMINATION_WORKAROUND)
  float v = (s * fp64.ONE - a) * fp64.ONE;
  float err = (a - (s - v) * fp64.ONE) * fp64.ONE * fp64.ONE * fp64.ONE - (b + v);
#else
  float v = s - a;
  float err = (a - (s - v)) - (b + v);
#endif
  return vec2(s, err);
}

vec2 twoSqr(float a) {
  float prod = a * a;
  vec2 a_fp64 = split(a);
#if defined(LUMA_FP64_CODE_ELIMINATION_WORKAROUND)
  float err = ((a_fp64.x * a_fp64.x - prod) * fp64.ONE + 2.0 * a_fp64.x *
    a_fp64.y * fp64.ONE * fp64.ONE) + a_fp64.y * a_fp64.y * fp64.ONE * fp64.ONE * fp64.ONE;
#else
  float err = ((a_fp64.x * a_fp64.x - prod) + 2.0 * a_fp64.x * a_fp64.y) + a_fp64.y * a_fp64.y;
#endif
  return vec2(prod, err);
}

vec2 twoProd(float a, float b) {
  float prod = a * b;
  vec2 a_fp64 = split(a);
  vec2 b_fp64 = split(b);
  // twoProd is especially sensitive because mul_fp64 and div_fp64 both depend
  // on the split terms and cross terms staying in the original evaluation
  // order. If the compiler folds or reassociates them, the low part tends to
  // collapse to zero or NaN on some drivers.
  float highProduct = prevent_fp64_optimization(a_fp64.x * b_fp64.x);
  float crossProduct1 = prevent_fp64_optimization(a_fp64.x * b_fp64.y);
  float crossProduct2 = prevent_fp64_optimization(a_fp64.y * b_fp64.x);
  float lowProduct = prevent_fp64_optimization(a_fp64.y * b_fp64.y);
#if defined(LUMA_FP64_CODE_ELIMINATION_WORKAROUND)
  float err1 = (highProduct - prod) * fp64.ONE;
  float err2 = crossProduct1 * fp64.ONE * fp64.ONE;
  float err3 = crossProduct2 * fp64.ONE * fp64.ONE * fp64.ONE;
  float err4 = lowProduct * fp64.ONE * fp64.ONE * fp64.ONE * fp64.ONE;
#else
  float err1 = highProduct - prod;
  float err2 = crossProduct1;
  float err3 = crossProduct2;
  float err4 = lowProduct;
#endif
  float err = ((err1 + err2) + err3) + err4;
  return vec2(prod, err);
}

vec2 sum_fp64(vec2 a, vec2 b) {
  vec2 s, t;
  s = twoSum(a.x, b.x);
  t = twoSum(a.y, b.y);
  s.y += t.x;
  s = quickTwoSum(s.x, s.y);
  s.y += t.y;
  s = quickTwoSum(s.x, s.y);
  return s;
}

vec2 sub_fp64(vec2 a, vec2 b) {
  vec2 s, t;
  s = twoSub(a.x, b.x);
  t = twoSub(a.y, b.y);
  s.y += t.x;
  s = quickTwoSum(s.x, s.y);
  s.y += t.y;
  s = quickTwoSum(s.x, s.y);
  return s;
}

vec2 mul_fp64(vec2 a, vec2 b) {
  vec2 prod = twoProd(a.x, b.x);
  // y component is for the error
  prod.y += a.x * b.y;
#if defined(LUMA_FP64_HIGH_BITS_OVERFLOW_WORKAROUND)
  prod = split2(prod);
#endif
  prod = quickTwoSum(prod.x, prod.y);
  prod.y += a.y * b.x;
#if defined(LUMA_FP64_HIGH_BITS_OVERFLOW_WORKAROUND)
  prod = split2(prod);
#endif
  prod = quickTwoSum(prod.x, prod.y);
  return prod;
}

vec2 div_fp64(vec2 a, vec2 b) {
  float xn = 1.0 / b.x;
#if defined(LUMA_FP64_HIGH_BITS_OVERFLOW_WORKAROUND)
  vec2 yn = mul_fp64(a, vec2(xn, 0));
#else
  vec2 yn = a * xn;
#endif
  float diff = (sub_fp64(a, mul_fp64(b, yn))).x;
  vec2 prod = twoProd(xn, diff);
  return sum_fp64(yn, prod);
}

vec2 sqrt_fp64(vec2 a) {
  if (a.x == 0.0 && a.y == 0.0) return vec2(0.0, 0.0);
  if (a.x < 0.0) return vec2(0.0 / 0.0, 0.0 / 0.0);

  float x = 1.0 / sqrt(a.x);
  float yn = a.x * x;
#if defined(LUMA_FP64_CODE_ELIMINATION_WORKAROUND)
  vec2 yn_sqr = twoSqr(yn) * fp64.ONE;
#else
  vec2 yn_sqr = twoSqr(yn);
#endif
  float diff = sub_fp64(a, yn_sqr).x;
  vec2 prod = twoProd(x * 0.5, diff);
#if defined(LUMA_FP64_HIGH_BITS_OVERFLOW_WORKAROUND)
  return sum_fp64(split(yn), prod);
#else
  return sum_fp64(vec2(yn, 0.0), prod);
#endif
}
`;
/**
* 64bit arithmetic: add, sub, mul, div (small subset of fp64 module)
*/
var fp64arithmetic = {
	name: "fp64arithmetic",
	source: `\
struct Fp64ArithmeticUniforms {
  ONE: f32,
  SPLIT: f32,
};

@group(0) @binding(auto) var<uniform> fp64arithmetic : Fp64ArithmeticUniforms;

fn fp64_nan(seed: f32) -> f32 {
  let nanBits = 0x7fc00000u | select(0u, 1u, seed < 0.0);
  return bitcast<f32>(nanBits);
}

fn fp64_runtime_zero() -> f32 {
  return fp64arithmetic.ONE * 0.0;
}

fn prevent_fp64_optimization(value: f32) -> f32 {
#ifdef LUMA_FP64_CODE_ELIMINATION_WORKAROUND
  return value + fp64_runtime_zero();
#else
  return value;
#endif
}

fn split(a: f32) -> vec2f {
  let splitValue = prevent_fp64_optimization(fp64arithmetic.SPLIT + fp64_runtime_zero());
  let t = prevent_fp64_optimization(a * splitValue);
  let temp = prevent_fp64_optimization(t - a);
  let aHi = prevent_fp64_optimization(t - temp);
  let aLo = prevent_fp64_optimization(a - aHi);
  return vec2f(aHi, aLo);
}

fn split2(a: vec2f) -> vec2f {
  var b = split(a.x);
  b.y = b.y + a.y;
  return b;
}

fn quickTwoSum(a: f32, b: f32) -> vec2f {
#ifdef LUMA_FP64_CODE_ELIMINATION_WORKAROUND
  let sum = prevent_fp64_optimization((a + b) * fp64arithmetic.ONE);
  let err = prevent_fp64_optimization(b - (sum - a) * fp64arithmetic.ONE);
#else
  let sum = prevent_fp64_optimization(a + b);
  let err = prevent_fp64_optimization(b - (sum - a));
#endif
  return vec2f(sum, err);
}

fn twoSum(a: f32, b: f32) -> vec2f {
  let s = prevent_fp64_optimization(a + b);
#ifdef LUMA_FP64_CODE_ELIMINATION_WORKAROUND
  let v = prevent_fp64_optimization((s * fp64arithmetic.ONE - a) * fp64arithmetic.ONE);
  let err =
    prevent_fp64_optimization((a - (s - v) * fp64arithmetic.ONE) *
      fp64arithmetic.ONE *
      fp64arithmetic.ONE *
      fp64arithmetic.ONE) +
    prevent_fp64_optimization(b - v);
#else
  let v = prevent_fp64_optimization(s - a);
  let err = prevent_fp64_optimization(a - (s - v)) + prevent_fp64_optimization(b - v);
#endif
  return vec2f(s, err);
}

fn twoSub(a: f32, b: f32) -> vec2f {
  let s = prevent_fp64_optimization(a - b);
#ifdef LUMA_FP64_CODE_ELIMINATION_WORKAROUND
  let v = prevent_fp64_optimization((s * fp64arithmetic.ONE - a) * fp64arithmetic.ONE);
  let err =
    prevent_fp64_optimization((a - (s - v) * fp64arithmetic.ONE) *
      fp64arithmetic.ONE *
      fp64arithmetic.ONE *
      fp64arithmetic.ONE) -
    prevent_fp64_optimization(b + v);
#else
  let v = prevent_fp64_optimization(s - a);
  let err = prevent_fp64_optimization(a - (s - v)) - prevent_fp64_optimization(b + v);
#endif
  return vec2f(s, err);
}

fn twoSqr(a: f32) -> vec2f {
  let prod = prevent_fp64_optimization(a * a);
  let aFp64 = split(a);
  let highProduct = prevent_fp64_optimization(aFp64.x * aFp64.x);
  let crossProduct = prevent_fp64_optimization(2.0 * aFp64.x * aFp64.y);
  let lowProduct = prevent_fp64_optimization(aFp64.y * aFp64.y);
#ifdef LUMA_FP64_CODE_ELIMINATION_WORKAROUND
  let err =
    (prevent_fp64_optimization(highProduct - prod) * fp64arithmetic.ONE +
      crossProduct * fp64arithmetic.ONE * fp64arithmetic.ONE) +
    lowProduct * fp64arithmetic.ONE * fp64arithmetic.ONE * fp64arithmetic.ONE;
#else
  let err = ((prevent_fp64_optimization(highProduct - prod) + crossProduct) + lowProduct);
#endif
  return vec2f(prod, err);
}

fn twoProd(a: f32, b: f32) -> vec2f {
  let prod = prevent_fp64_optimization(a * b);
  let aFp64 = split(a);
  let bFp64 = split(b);
  let highProduct = prevent_fp64_optimization(aFp64.x * bFp64.x);
  let crossProduct1 = prevent_fp64_optimization(aFp64.x * bFp64.y);
  let crossProduct2 = prevent_fp64_optimization(aFp64.y * bFp64.x);
  let lowProduct = prevent_fp64_optimization(aFp64.y * bFp64.y);
#ifdef LUMA_FP64_CODE_ELIMINATION_WORKAROUND
  let err1 = (highProduct - prod) * fp64arithmetic.ONE;
  let err2 = crossProduct1 * fp64arithmetic.ONE * fp64arithmetic.ONE;
  let err3 = crossProduct2 * fp64arithmetic.ONE * fp64arithmetic.ONE * fp64arithmetic.ONE;
  let err4 =
    lowProduct *
    fp64arithmetic.ONE *
    fp64arithmetic.ONE *
    fp64arithmetic.ONE *
    fp64arithmetic.ONE;
#else
  let err1 = highProduct - prod;
  let err2 = crossProduct1;
  let err3 = crossProduct2;
  let err4 = lowProduct;
#endif
  let err12InputA = prevent_fp64_optimization(err1);
  let err12InputB = prevent_fp64_optimization(err2);
  let err12 = prevent_fp64_optimization(err12InputA + err12InputB);
  let err123InputA = prevent_fp64_optimization(err12);
  let err123InputB = prevent_fp64_optimization(err3);
  let err123 = prevent_fp64_optimization(err123InputA + err123InputB);
  let err1234InputA = prevent_fp64_optimization(err123);
  let err1234InputB = prevent_fp64_optimization(err4);
  let err = prevent_fp64_optimization(err1234InputA + err1234InputB);
  return vec2f(prod, err);
}

fn sum_fp64(a: vec2f, b: vec2f) -> vec2f {
  var s = twoSum(a.x, b.x);
  let t = twoSum(a.y, b.y);
  s.y = prevent_fp64_optimization(s.y + t.x);
  s = quickTwoSum(s.x, s.y);
  s.y = prevent_fp64_optimization(s.y + t.y);
  s = quickTwoSum(s.x, s.y);
  return s;
}

fn sub_fp64(a: vec2f, b: vec2f) -> vec2f {
  var s = twoSub(a.x, b.x);
  let t = twoSub(a.y, b.y);
  s.y = prevent_fp64_optimization(s.y + t.x);
  s = quickTwoSum(s.x, s.y);
  s.y = prevent_fp64_optimization(s.y + t.y);
  s = quickTwoSum(s.x, s.y);
  return s;
}

fn mul_fp64(a: vec2f, b: vec2f) -> vec2f {
  var prod = twoProd(a.x, b.x);
  let crossProduct1 = prevent_fp64_optimization(a.x * b.y);
  prod.y = prevent_fp64_optimization(prod.y + crossProduct1);
#ifdef LUMA_FP64_HIGH_BITS_OVERFLOW_WORKAROUND
  prod = split2(prod);
#endif
  prod = quickTwoSum(prod.x, prod.y);
  let crossProduct2 = prevent_fp64_optimization(a.y * b.x);
  prod.y = prevent_fp64_optimization(prod.y + crossProduct2);
#ifdef LUMA_FP64_HIGH_BITS_OVERFLOW_WORKAROUND
  prod = split2(prod);
#endif
  prod = quickTwoSum(prod.x, prod.y);
  return prod;
}

fn div_fp64(a: vec2f, b: vec2f) -> vec2f {
  let xn = prevent_fp64_optimization(1.0 / b.x);
  let yn = mul_fp64(a, vec2f(xn, fp64_runtime_zero()));
  let diff = prevent_fp64_optimization(sub_fp64(a, mul_fp64(b, yn)).x);
  let prod = twoProd(xn, diff);
  return sum_fp64(yn, prod);
}

fn sqrt_fp64(a: vec2f) -> vec2f {
  if (a.x == 0.0 && a.y == 0.0) {
    return vec2f(0.0, 0.0);
  }
  if (a.x < 0.0) {
    let nanValue = fp64_nan(a.x);
    return vec2f(nanValue, nanValue);
  }

  let x = prevent_fp64_optimization(1.0 / sqrt(a.x));
  let yn = prevent_fp64_optimization(a.x * x);
#ifdef LUMA_FP64_CODE_ELIMINATION_WORKAROUND
  let ynSqr = twoSqr(yn) * fp64arithmetic.ONE;
#else
  let ynSqr = twoSqr(yn);
#endif
  let diff = prevent_fp64_optimization(sub_fp64(a, ynSqr).x);
  let prod = twoProd(prevent_fp64_optimization(x * 0.5), diff);
#ifdef LUMA_FP64_HIGH_BITS_OVERFLOW_WORKAROUND
  return sum_fp64(split(yn), prod);
#else
  return sum_fp64(vec2f(yn, 0.0), prod);
#endif
}
`,
	fs: fp64arithmeticShader,
	vs: fp64arithmeticShader,
	defaultUniforms: {
		ONE: 1,
		SPLIT: 4097
	},
	uniformTypes: {
		ONE: "f32",
		SPLIT: "f32"
	},
	fp64ify,
	fp64LowPart,
	fp64ifyMatrix4
};
//#endregion
//#region node_modules/@luma.gl/core/dist/adapter/resources/compute-pipeline.js
/**
* A compiled and linked shader program for compute
*/
var ComputePipeline = class ComputePipeline extends Resource {
	get [Symbol.toStringTag]() {
		return "ComputePipeline";
	}
	hash = "";
	/** The merged shader layout */
	shaderLayout;
	constructor(device, props) {
		super(device, props, ComputePipeline.defaultProps);
		this.shaderLayout = props.shaderLayout;
	}
	static defaultProps = {
		...Resource.defaultProps,
		shader: void 0,
		entryPoint: void 0,
		constants: {},
		shaderLayout: void 0
	};
};
//#endregion
//#region node_modules/@luma.gl/core/dist/factories/pipeline-factory.js
/**
* Efficiently creates / caches pipelines
*/
var PipelineFactory = class PipelineFactory {
	static defaultProps = { ...RenderPipeline.defaultProps };
	/** Get the singleton default pipeline factory for the specified device */
	static getDefaultPipelineFactory(device) {
		const moduleData = device.getModuleData("@luma.gl/core");
		moduleData.defaultPipelineFactory ||= new PipelineFactory(device);
		return moduleData.defaultPipelineFactory;
	}
	device;
	_hashCounter = 0;
	_hashes = {};
	_renderPipelineCache = {};
	_computePipelineCache = {};
	_sharedRenderPipelineCache = {};
	get [Symbol.toStringTag]() {
		return "PipelineFactory";
	}
	toString() {
		return `PipelineFactory(${this.device.id})`;
	}
	constructor(device) {
		this.device = device;
	}
	/**
	* WebGL has two cache layers with different priorities:
	* - `_sharedRenderPipelineCache` owns `WEBGLSharedRenderPipeline` / `WebGLProgram` reuse.
	* - `_renderPipelineCache` owns `RenderPipeline` wrapper reuse.
	*
	* Shared WebGL program reuse is the hard requirement. Wrapper reuse is beneficial,
	* but wrapper cache misses are acceptable if that keeps the cache logic simple and
	* prevents incorrect cache hits.
	*
	* In particular, wrapper hash logic must never force program creation or linked-program
	* introspection just to decide whether a shared WebGL program can be reused.
	*/
	/** Return a RenderPipeline matching supplied props. Reuses an equivalent pipeline if already created. */
	createRenderPipeline(props) {
		if (!this.device.props._cachePipelines) return this.device.createRenderPipeline(props);
		const allProps = {
			...RenderPipeline.defaultProps,
			...props
		};
		const cache = this._renderPipelineCache;
		const hash = this._hashRenderPipeline(allProps);
		let pipeline = cache[hash]?.resource;
		if (!pipeline) {
			const sharedRenderPipeline = this.device.type === "webgl" && this.device.props._sharePipelines ? this.createSharedRenderPipeline(allProps) : void 0;
			pipeline = this.device.createRenderPipeline({
				...allProps,
				id: allProps.id ? `${allProps.id}-cached` : uid$1("unnamed-cached"),
				_sharedRenderPipeline: sharedRenderPipeline
			});
			pipeline.hash = hash;
			cache[hash] = {
				resource: pipeline,
				useCount: 1
			};
			if (this.device.props.debugFactories) log.log(3, `${this}: ${pipeline} created, count=${cache[hash].useCount}`)();
		} else {
			cache[hash].useCount++;
			if (this.device.props.debugFactories) log.log(3, `${this}: ${cache[hash].resource} reused, count=${cache[hash].useCount}, (id=${props.id})`)();
		}
		return pipeline;
	}
	/** Return a ComputePipeline matching supplied props. Reuses an equivalent pipeline if already created. */
	createComputePipeline(props) {
		if (!this.device.props._cachePipelines) return this.device.createComputePipeline(props);
		const allProps = {
			...ComputePipeline.defaultProps,
			...props
		};
		const cache = this._computePipelineCache;
		const hash = this._hashComputePipeline(allProps);
		let pipeline = cache[hash]?.resource;
		if (!pipeline) {
			pipeline = this.device.createComputePipeline({
				...allProps,
				id: allProps.id ? `${allProps.id}-cached` : void 0
			});
			pipeline.hash = hash;
			cache[hash] = {
				resource: pipeline,
				useCount: 1
			};
			if (this.device.props.debugFactories) log.log(3, `${this}: ${pipeline} created, count=${cache[hash].useCount}`)();
		} else {
			cache[hash].useCount++;
			if (this.device.props.debugFactories) log.log(3, `${this}: ${cache[hash].resource} reused, count=${cache[hash].useCount}, (id=${props.id})`)();
		}
		return pipeline;
	}
	release(pipeline) {
		if (!this.device.props._cachePipelines) {
			pipeline.destroy();
			return;
		}
		const cache = this._getCache(pipeline);
		const hash = pipeline.hash;
		cache[hash].useCount--;
		if (cache[hash].useCount === 0) {
			this._destroyPipeline(pipeline);
			if (this.device.props.debugFactories) log.log(3, `${this}: ${pipeline} released and destroyed`)();
		} else if (cache[hash].useCount < 0) {
			log.error(`${this}: ${pipeline} released, useCount < 0, resetting`)();
			cache[hash].useCount = 0;
		} else if (this.device.props.debugFactories) log.log(3, `${this}: ${pipeline} released, count=${cache[hash].useCount}`)();
	}
	createSharedRenderPipeline(props) {
		const sharedPipelineHash = this._hashSharedRenderPipeline(props);
		let sharedCacheItem = this._sharedRenderPipelineCache[sharedPipelineHash];
		if (!sharedCacheItem) {
			sharedCacheItem = {
				resource: this.device._createSharedRenderPipelineWebGL(props),
				useCount: 0
			};
			this._sharedRenderPipelineCache[sharedPipelineHash] = sharedCacheItem;
		}
		sharedCacheItem.useCount++;
		return sharedCacheItem.resource;
	}
	releaseSharedRenderPipeline(pipeline) {
		if (!pipeline.sharedRenderPipeline) return;
		const sharedPipelineHash = this._hashSharedRenderPipeline(pipeline.sharedRenderPipeline.props);
		const sharedCacheItem = this._sharedRenderPipelineCache[sharedPipelineHash];
		if (!sharedCacheItem) return;
		sharedCacheItem.useCount--;
		if (sharedCacheItem.useCount === 0) {
			sharedCacheItem.resource.destroy();
			delete this._sharedRenderPipelineCache[sharedPipelineHash];
		}
	}
	/** Destroy a cached pipeline, removing it from the cache if configured to do so. */
	_destroyPipeline(pipeline) {
		const cache = this._getCache(pipeline);
		if (!this.device.props._destroyPipelines) return false;
		delete cache[pipeline.hash];
		pipeline.destroy();
		if (pipeline instanceof RenderPipeline) this.releaseSharedRenderPipeline(pipeline);
		return true;
	}
	/** Get the appropriate cache for the type of pipeline */
	_getCache(pipeline) {
		let cache;
		if (pipeline instanceof ComputePipeline) cache = this._computePipelineCache;
		if (pipeline instanceof RenderPipeline) cache = this._renderPipelineCache;
		if (!cache) throw new Error(`${this}`);
		if (!cache[pipeline.hash]) throw new Error(`${this}: ${pipeline} matched incorrect entry`);
		return cache;
	}
	/** Calculate a hash based on all the inputs for a compute pipeline */
	_hashComputePipeline(props) {
		const { type } = this.device;
		return `${type}/C/${this._getHash(props.shader.source)}SL${this._getHash(JSON.stringify(props.shaderLayout))}`;
	}
	/** Calculate a hash based on all the inputs for a render pipeline */
	_hashRenderPipeline(props) {
		const vsHash = props.vs ? this._getHash(props.vs.source) : 0;
		const fsHash = props.fs ? this._getHash(props.fs.source) : 0;
		const varyingHash = this._getWebGLVaryingHash(props);
		const shaderLayoutHash = this._getHash(JSON.stringify(props.shaderLayout));
		const bufferLayoutHash = this._getHash(JSON.stringify(props.bufferLayout));
		const { type } = this.device;
		switch (type) {
			case "webgl":
				const webglParameterHash = this._getHash(JSON.stringify(props.parameters));
				return `${type}/R/${vsHash}/${fsHash}V${varyingHash}T${props.topology}P${webglParameterHash}SL${shaderLayoutHash}BL${bufferLayoutHash}`;
			default:
				const entryPointHash = this._getHash(JSON.stringify({
					vertexEntryPoint: props.vertexEntryPoint,
					fragmentEntryPoint: props.fragmentEntryPoint
				}));
				const parameterHash = this._getHash(JSON.stringify(props.parameters));
				const attachmentHash = this._getWebGPUAttachmentHash(props);
				return `${type}/R/${vsHash}/${fsHash}V${varyingHash}T${props.topology}EP${entryPointHash}P${parameterHash}SL${shaderLayoutHash}BL${bufferLayoutHash}A${attachmentHash}`;
		}
	}
	_hashSharedRenderPipeline(props) {
		return `webgl/S/${props.vs ? this._getHash(props.vs.source) : 0}/${props.fs ? this._getHash(props.fs.source) : 0}V${this._getWebGLVaryingHash(props)}`;
	}
	_getHash(key) {
		if (this._hashes[key] === void 0) this._hashes[key] = this._hashCounter++;
		return this._hashes[key];
	}
	_getWebGLVaryingHash(props) {
		const { varyings = [], bufferMode = null } = props;
		return this._getHash(JSON.stringify({
			varyings,
			bufferMode
		}));
	}
	_getWebGPUAttachmentHash(props) {
		const colorAttachmentFormats = props.colorAttachmentFormats ?? [this.device.preferredColorFormat];
		const depthStencilAttachmentFormat = props.parameters?.depthWriteEnabled ? props.depthStencilAttachmentFormat || this.device.preferredDepthFormat : null;
		return this._getHash(JSON.stringify({
			colorAttachmentFormats,
			depthStencilAttachmentFormat
		}));
	}
};
//#endregion
//#region node_modules/@luma.gl/core/dist/factories/shader-factory.js
/** Manages a cached pool of Shaders for reuse. */
var ShaderFactory = class ShaderFactory {
	static defaultProps = { ...Shader.defaultProps };
	/** Returns the default ShaderFactory for the given {@link Device}, creating one if necessary. */
	static getDefaultShaderFactory(device) {
		const moduleData = device.getModuleData("@luma.gl/core");
		moduleData.defaultShaderFactory ||= new ShaderFactory(device);
		return moduleData.defaultShaderFactory;
	}
	device;
	_cache = {};
	get [Symbol.toStringTag]() {
		return "ShaderFactory";
	}
	toString() {
		return `${this[Symbol.toStringTag]}(${this.device.id})`;
	}
	/** @internal */
	constructor(device) {
		this.device = device;
	}
	/** Requests a {@link Shader} from the cache, creating a new Shader only if necessary. */
	createShader(props) {
		if (!this.device.props._cacheShaders) return this.device.createShader(props);
		const key = this._hashShader(props);
		let cacheEntry = this._cache[key];
		if (!cacheEntry) {
			const resource = this.device.createShader({
				...props,
				id: props.id ? `${props.id}-cached` : void 0
			});
			this._cache[key] = cacheEntry = {
				resource,
				useCount: 1
			};
			if (this.device.props.debugFactories) log.log(3, `${this}: Created new shader ${resource.id}`)();
		} else {
			cacheEntry.useCount++;
			if (this.device.props.debugFactories) log.log(3, `${this}: Reusing shader ${cacheEntry.resource.id} count=${cacheEntry.useCount}`)();
		}
		return cacheEntry.resource;
	}
	/** Releases a previously-requested {@link Shader}, destroying it if no users remain. */
	release(shader) {
		if (!this.device.props._cacheShaders) {
			shader.destroy();
			return;
		}
		const key = this._hashShader(shader);
		const cacheEntry = this._cache[key];
		if (cacheEntry) {
			cacheEntry.useCount--;
			if (cacheEntry.useCount === 0) {
				if (this.device.props._destroyShaders) {
					delete this._cache[key];
					cacheEntry.resource.destroy();
					if (this.device.props.debugFactories) log.log(3, `${this}: Releasing shader ${shader.id}, destroyed`)();
				}
			} else if (cacheEntry.useCount < 0) throw new Error(`ShaderFactory: Shader ${shader.id} released too many times`);
			else if (this.device.props.debugFactories) log.log(3, `${this}: Releasing shader ${shader.id} count=${cacheEntry.useCount}`)();
		}
	}
	_hashShader(value) {
		return `${value.stage}:${value.source}`;
	}
};
//#endregion
//#region node_modules/@luma.gl/core/dist/shadertypes/shader-types/shader-block-layout.js
/**
* Builds a deterministic shader-block layout from composite shader type declarations.
*
* The returned value is pure layout metadata. It records the packed field
* offsets and exact packed byte length, but it does not allocate buffers or
* serialize values.
*/
function makeShaderBlockLayout(uniformTypes, options = {}) {
	const copiedUniformTypes = { ...uniformTypes };
	const layout = options.layout ?? "std140";
	const fields = {};
	let size = 0;
	for (const [key, uniformType] of Object.entries(copiedUniformTypes)) size = addToLayout(fields, key, uniformType, size, layout);
	size = alignTo(size, getTypeAlignment(copiedUniformTypes, layout));
	return {
		layout,
		byteLength: size * 4,
		uniformTypes: copiedUniformTypes,
		fields
	};
}
/**
* Returns the layout metadata for a scalar, vector, or matrix leaf type.
*
* The result includes both the occupied size in 32-bit words and the alignment
* requirement that must be applied before placing the value in a shader block.
*/
function getLeafLayoutInfo(type, layout) {
	const resolvedType = resolveVariableShaderTypeAlias(type);
	const decodedType = getVariableShaderTypeInfo(resolvedType);
	const matrixMatch = /^mat(\d)x(\d)<.+>$/.exec(resolvedType);
	if (matrixMatch) {
		const columns = Number(matrixMatch[1]);
		const rows = Number(matrixMatch[2]);
		const columnInfo = getVectorLayoutInfo(rows, resolvedType, decodedType.type, layout);
		const columnStride = getMatrixColumnStride(columnInfo.size, columnInfo.alignment, layout);
		return {
			alignment: columnInfo.alignment,
			size: columns * columnStride,
			components: columns * rows,
			columns,
			rows,
			columnStride,
			shaderType: resolvedType,
			type: decodedType.type
		};
	}
	const vectorMatch = /^vec(\d)<.+>$/.exec(resolvedType);
	if (vectorMatch) return getVectorLayoutInfo(Number(vectorMatch[1]), resolvedType, decodedType.type, layout);
	return {
		alignment: 1,
		size: 1,
		components: 1,
		columns: 1,
		rows: 1,
		columnStride: 1,
		shaderType: resolvedType,
		type: decodedType.type
	};
}
/**
* Type guard for composite struct declarations.
*/
function isCompositeShaderTypeStruct(value) {
	return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
/**
* Recursively adds a composite type to the flattened field map.
*
* @returns The next free 32-bit-word offset after the inserted type.
*/
function addToLayout(fields, name, type, offset, layout) {
	if (typeof type === "string") {
		const info = getLeafLayoutInfo(type, layout);
		const alignedOffset = alignTo(offset, info.alignment);
		fields[name] = {
			offset: alignedOffset,
			...info
		};
		return alignedOffset + info.size;
	}
	if (Array.isArray(type)) {
		if (Array.isArray(type[0])) throw new Error(`Nested arrays are not supported for ${name}`);
		const elementType = type[0];
		const length = type[1];
		const stride = getArrayStride(elementType, layout);
		const arrayOffset = alignTo(offset, getTypeAlignment(type, layout));
		for (let i = 0; i < length; i++) addToLayout(fields, `${name}[${i}]`, elementType, arrayOffset + i * stride, layout);
		return arrayOffset + stride * length;
	}
	if (isCompositeShaderTypeStruct(type)) {
		const structAlignment = getTypeAlignment(type, layout);
		let structOffset = alignTo(offset, structAlignment);
		for (const [memberName, memberType] of Object.entries(type)) structOffset = addToLayout(fields, `${name}.${memberName}`, memberType, structOffset, layout);
		return alignTo(structOffset, structAlignment);
	}
	throw new Error(`Unsupported CompositeShaderType for ${name}`);
}
/**
* Returns the occupied size of a composite type in 32-bit words.
*/
function getTypeSize(type, layout) {
	if (typeof type === "string") return getLeafLayoutInfo(type, layout).size;
	if (Array.isArray(type)) {
		const elementType = type[0];
		const length = type[1];
		if (Array.isArray(elementType)) throw new Error("Nested arrays are not supported");
		return getArrayStride(elementType, layout) * length;
	}
	let size = 0;
	for (const memberType of Object.values(type)) {
		const compositeMemberType = memberType;
		size = alignTo(size, getTypeAlignment(compositeMemberType, layout));
		size += getTypeSize(compositeMemberType, layout);
	}
	return alignTo(size, getTypeAlignment(type, layout));
}
/**
* Returns the required alignment of a composite type in 32-bit words.
*/
function getTypeAlignment(type, layout) {
	if (typeof type === "string") return getLeafLayoutInfo(type, layout).alignment;
	if (Array.isArray(type)) {
		const elementType = type[0];
		const elementAlignment = getTypeAlignment(elementType, layout);
		return uses16ByteArrayAlignment(layout) ? Math.max(elementAlignment, 4) : elementAlignment;
	}
	let maxAlignment = 1;
	for (const memberType of Object.values(type)) {
		const memberAlignment = getTypeAlignment(memberType, layout);
		maxAlignment = Math.max(maxAlignment, memberAlignment);
	}
	return uses16ByteStructAlignment(layout) ? Math.max(maxAlignment, 4) : maxAlignment;
}
/**
* Returns the layout metadata for a vector leaf type.
*/
function getVectorLayoutInfo(components, shaderType, type, layout) {
	return {
		alignment: components === 2 ? 2 : 4,
		size: components === 3 ? 3 : components,
		components,
		columns: 1,
		rows: components,
		columnStride: components === 3 ? 3 : components,
		shaderType,
		type
	};
}
/**
* Returns the stride of an array element in 32-bit words.
*
* This includes any layout-specific padding between adjacent array elements.
*/
function getArrayStride(elementType, layout) {
	return getArrayLikeStride(getTypeSize(elementType, layout), getTypeAlignment(elementType, layout), layout);
}
/**
* Returns the common stride rule shared by array-like elements in the target layout.
*/
function getArrayLikeStride(size, alignment, layout) {
	return alignTo(size, uses16ByteArrayAlignment(layout) ? 4 : alignment);
}
/**
* Returns the stride of a matrix column in 32-bit words.
*/
function getMatrixColumnStride(size, alignment, layout) {
	return layout === "std140" ? 4 : alignTo(size, alignment);
}
/**
* Returns `true` when arrays must be rounded up to 16-byte boundaries.
*/
function uses16ByteArrayAlignment(layout) {
	return layout === "std140" || layout === "wgsl-uniform";
}
/**
* Returns `true` when structs must be rounded up to 16-byte boundaries.
*/
function uses16ByteStructAlignment(layout) {
	return layout === "std140" || layout === "wgsl-uniform";
}
//#endregion
//#region node_modules/@luma.gl/core/dist/utils/is-array.js
/**
* Check is an array is a typed array
* @param value value to be tested
* @returns input as TypedArray, or null
* @todo this should be provided by @math.gl/types
*/
function isTypedArray(value) {
	return ArrayBuffer.isView(value) && !(value instanceof DataView);
}
/**
* Check is an array is a numeric array (typed array or array of numbers)
* @param value value to be tested
* @returns input as NumberArray, or null
* @todo this should be provided by @math.gl/types
*/
function isNumberArray(value) {
	if (Array.isArray(value)) return value.length === 0 || typeof value[0] === "number";
	return isTypedArray(value);
}
//#endregion
//#region node_modules/@luma.gl/core/dist/portable/shader-block-writer.js
/**
* Serializes nested JavaScript uniform values according to a {@link ShaderBlockLayout}.
*/
var ShaderBlockWriter = class {
	/** Layout metadata used to flatten and serialize values. */
	layout;
	/**
	* Creates a writer for a precomputed shader-block layout.
	*/
	constructor(layout) {
		this.layout = layout;
	}
	/**
	* Returns `true` if the flattened layout contains the given field.
	*/
	has(name) {
		return Boolean(this.layout.fields[name]);
	}
	/**
	* Returns offset and size metadata for a flattened field.
	*/
	get(name) {
		const entry = this.layout.fields[name];
		return entry ? {
			offset: entry.offset,
			size: entry.size
		} : void 0;
	}
	/**
	* Flattens nested composite values into leaf-path values understood by {@link UniformBlock}.
	*
	* Top-level values may be supplied either in nested object form matching the
	* declared composite shader types or as already-flattened leaf-path values.
	*/
	getFlatUniformValues(uniformValues) {
		const flattenedUniformValues = {};
		for (const [name, value] of Object.entries(uniformValues)) {
			const uniformType = this.layout.uniformTypes[name];
			if (uniformType) this._flattenCompositeValue(flattenedUniformValues, name, uniformType, value);
			else if (this.layout.fields[name]) flattenedUniformValues[name] = value;
		}
		return flattenedUniformValues;
	}
	/**
	* Serializes the supplied values into buffer-backed binary data.
	*
	* The returned view length matches {@link ShaderBlockLayout.byteLength}, which
	* is the exact packed size of the block.
	*/
	getData(uniformValues) {
		const buffer = getScratchArrayBuffer(this.layout.byteLength);
		new Uint8Array(buffer, 0, this.layout.byteLength).fill(0);
		const typedArrays = {
			i32: new Int32Array(buffer),
			u32: new Uint32Array(buffer),
			f32: new Float32Array(buffer),
			f16: new Uint16Array(buffer)
		};
		const flattenedUniformValues = this.getFlatUniformValues(uniformValues);
		for (const [name, value] of Object.entries(flattenedUniformValues)) this._writeLeafValue(typedArrays, name, value);
		return new Uint8Array(buffer, 0, this.layout.byteLength);
	}
	/**
	* Recursively flattens nested values using the declared composite shader type.
	*/
	_flattenCompositeValue(flattenedUniformValues, baseName, uniformType, value) {
		if (value === void 0) return;
		if (typeof uniformType === "string" || this.layout.fields[baseName]) {
			flattenedUniformValues[baseName] = value;
			return;
		}
		if (Array.isArray(uniformType)) {
			const elementType = uniformType[0];
			const length = uniformType[1];
			if (Array.isArray(elementType)) throw new Error(`Nested arrays are not supported for ${baseName}`);
			if (typeof elementType === "string" && isNumberArray(value)) {
				this._flattenPackedArray(flattenedUniformValues, baseName, elementType, length, value);
				return;
			}
			if (!Array.isArray(value)) {
				log.warn(`Unsupported uniform array value for ${baseName}:`, value)();
				return;
			}
			for (let index = 0; index < Math.min(value.length, length); index++) {
				const elementValue = value[index];
				if (elementValue === void 0) continue;
				this._flattenCompositeValue(flattenedUniformValues, `${baseName}[${index}]`, elementType, elementValue);
			}
			return;
		}
		if (isCompositeShaderTypeStruct(uniformType) && isCompositeUniformObject(value)) {
			for (const [key, subValue] of Object.entries(value)) {
				if (subValue === void 0) continue;
				const nestedName = `${baseName}.${key}`;
				this._flattenCompositeValue(flattenedUniformValues, nestedName, uniformType[key], subValue);
			}
			return;
		}
		log.warn(`Unsupported uniform value for ${baseName}:`, value)();
	}
	/**
	* Expands tightly packed numeric arrays into per-element leaf fields.
	*/
	_flattenPackedArray(flattenedUniformValues, baseName, elementType, length, value) {
		const numericValue = value;
		const packedElementLength = getLeafLayoutInfo(elementType, this.layout.layout).components;
		for (let index = 0; index < length; index++) {
			const start = index * packedElementLength;
			if (start >= numericValue.length) break;
			if (packedElementLength === 1) flattenedUniformValues[`${baseName}[${index}]`] = Number(numericValue[start]);
			else flattenedUniformValues[`${baseName}[${index}]`] = sliceNumericArray(value, start, start + packedElementLength);
		}
	}
	/**
	* Writes one flattened leaf value into its typed-array view.
	*/
	_writeLeafValue(typedArrays, name, value) {
		const entry = this.layout.fields[name];
		if (!entry) {
			log.warn(`Uniform ${name} not found in layout`)();
			return;
		}
		const { type, components, columns, rows, offset, columnStride } = entry;
		const array = typedArrays[type];
		if (components === 1) {
			array[offset] = Number(value);
			return;
		}
		const sourceValue = value;
		if (columns === 1) {
			for (let componentIndex = 0; componentIndex < components; componentIndex++) array[offset + componentIndex] = Number(sourceValue[componentIndex] ?? 0);
			return;
		}
		let sourceIndex = 0;
		for (let columnIndex = 0; columnIndex < columns; columnIndex++) {
			const columnOffset = offset + columnIndex * columnStride;
			for (let rowIndex = 0; rowIndex < rows; rowIndex++) array[columnOffset + rowIndex] = Number(sourceValue[sourceIndex++] ?? 0);
		}
	}
};
/**
* Type guard for nested uniform objects.
*/
function isCompositeUniformObject(value) {
	return Boolean(value) && typeof value === "object" && !Array.isArray(value) && !ArrayBuffer.isView(value);
}
/**
* Slices a numeric array-like value without changing its numeric representation.
*/
function sliceNumericArray(value, start, end) {
	return Array.prototype.slice.call(value, start, end);
}
//#endregion
//#region node_modules/@luma.gl/core/dist/utils/array-equal.js
var MAX_ELEMENTWISE_ARRAY_COMPARE_LENGTH = 128;
/** Test if two arrays are deep equal, with a small-array length limit that defaults to 16 */
function arrayEqual(a, b, limit = 16) {
	if (a === b) return true;
	const arrayA = a;
	const arrayB = b;
	if (!isNumberArray(arrayA) || !isNumberArray(arrayB)) return false;
	if (arrayA.length !== arrayB.length) return false;
	const maxCompareLength = Math.min(limit, MAX_ELEMENTWISE_ARRAY_COMPARE_LENGTH);
	if (arrayA.length > maxCompareLength) return false;
	for (let i = 0; i < arrayA.length; ++i) if (arrayB[i] !== arrayA[i]) return false;
	return true;
}
/** Copy a value */
function arrayCopy(a) {
	if (isNumberArray(a)) return a.slice();
	return a;
}
//#endregion
//#region node_modules/@luma.gl/core/dist/portable/uniform-block.js
/**
* A uniform block holds values of the of uniform values for one uniform block / buffer.
* It also does some book keeping on what has changed, to minimize unnecessary writes to uniform buffers.
*/
var UniformBlock = class {
	name;
	uniforms = {};
	modifiedUniforms = {};
	modified = true;
	bindingLayout = {};
	needsRedraw = "initialized";
	constructor(props) {
		this.name = props?.name || "unnamed";
		if (props?.name && props?.shaderLayout) {
			const binding = props?.shaderLayout.bindings?.find((binding_) => binding_.type === "uniform" && binding_.name === props?.name);
			if (!binding) throw new Error(props?.name);
			const uniformBlock = binding;
			for (const uniform of uniformBlock.uniforms || []) this.bindingLayout[uniform.name] = uniform;
		}
	}
	/** Set a map of uniforms */
	setUniforms(uniforms) {
		for (const [key, value] of Object.entries(uniforms)) {
			this._setUniform(key, value);
			if (!this.needsRedraw) this.setNeedsRedraw(`${this.name}.${key}=${value}`);
		}
	}
	setNeedsRedraw(reason) {
		this.needsRedraw = this.needsRedraw || reason;
	}
	/** Returns all uniforms */
	getAllUniforms() {
		this.modifiedUniforms = {};
		this.needsRedraw = false;
		return this.uniforms || {};
	}
	/** Set a single uniform */
	_setUniform(key, value) {
		if (arrayEqual(this.uniforms[key], value)) return;
		this.uniforms[key] = arrayCopy(value);
		this.modifiedUniforms[key] = true;
		this.modified = true;
	}
};
//#endregion
//#region node_modules/@luma.gl/core/dist/portable/uniform-store.js
/**
* Smallest buffer size that can be used for uniform buffers.
*
* This is an allocation policy rather than part of {@link ShaderBlockLayout}.
* Layouts report the exact packed size, while the store applies any minimum
* buffer-size rule when allocating GPU buffers.
*
* TODO - does this depend on device?
*/
var minUniformBufferSize = 1024;
/**
* A uniform store holds a uniform values for one or more uniform blocks,
* - It can generate binary data for any uniform buffer
* - It can manage a uniform buffer for each block
* - It can update managed uniform buffers with a single call
* - It performs some book keeping on what has changed to minimize unnecessary writes to uniform buffers.
*/
var UniformStore = class {
	/** Device used to infer layout and allocate buffers. */
	device;
	/** Stores the uniform values for each uniform block */
	uniformBlocks = /* @__PURE__ */ new Map();
	/** Flattened layout metadata for each block. */
	shaderBlockLayouts = /* @__PURE__ */ new Map();
	/** Serializers for block-backed uniform data. */
	shaderBlockWriters = /* @__PURE__ */ new Map();
	/** Actual buffer for the blocks */
	uniformBuffers = /* @__PURE__ */ new Map();
	/**
	* Creates a new {@link UniformStore} for the supplied device and block definitions.
	*/
	constructor(device, blocks) {
		this.device = device;
		for (const [bufferName, block] of Object.entries(blocks)) {
			const uniformBufferName = bufferName;
			const shaderBlockLayout = makeShaderBlockLayout(block.uniformTypes ?? {}, { layout: block.layout ?? getDefaultUniformBufferLayout(device) });
			const shaderBlockWriter = new ShaderBlockWriter(shaderBlockLayout);
			this.shaderBlockLayouts.set(uniformBufferName, shaderBlockLayout);
			this.shaderBlockWriters.set(uniformBufferName, shaderBlockWriter);
			const uniformBlock = new UniformBlock({ name: bufferName });
			uniformBlock.setUniforms(shaderBlockWriter.getFlatUniformValues(block.defaultUniforms || {}));
			this.uniformBlocks.set(uniformBufferName, uniformBlock);
		}
	}
	/** Destroy any managed uniform buffers */
	destroy() {
		for (const uniformBuffer of this.uniformBuffers.values()) uniformBuffer.destroy();
	}
	/**
	* Set uniforms
	*
	* Makes all group properties partial and eagerly propagates changes to any
	* managed GPU buffers.
	*/
	setUniforms(uniforms) {
		for (const [blockName, uniformValues] of Object.entries(uniforms)) {
			const uniformBufferName = blockName;
			const flattenedUniforms = this.shaderBlockWriters.get(uniformBufferName)?.getFlatUniformValues(uniformValues || {});
			this.uniformBlocks.get(uniformBufferName)?.setUniforms(flattenedUniforms || {});
		}
		this.updateUniformBuffers();
	}
	/**
	* Returns the allocation size for the named uniform buffer.
	*
	* This may exceed the packed layout size because minimum buffer-size policy is
	* applied at the store layer.
	*/
	getUniformBufferByteLength(uniformBufferName) {
		const packedByteLength = this.shaderBlockLayouts.get(uniformBufferName)?.byteLength || 0;
		return Math.max(packedByteLength, minUniformBufferSize);
	}
	/**
	* Returns packed binary data that can be uploaded to the named uniform buffer.
	*
	* The returned view length matches the packed block size and is not padded to
	* the store's minimum allocation size.
	*/
	getUniformBufferData(uniformBufferName) {
		const uniformValues = this.uniformBlocks.get(uniformBufferName)?.getAllUniforms() || {};
		return this.shaderBlockWriters.get(uniformBufferName)?.getData(uniformValues) || new Uint8Array(0);
	}
	/**
	* Creates an unmanaged uniform buffer initialized with the current or supplied values.
	*/
	createUniformBuffer(uniformBufferName, uniforms) {
		if (uniforms) this.setUniforms(uniforms);
		const byteLength = this.getUniformBufferByteLength(uniformBufferName);
		const uniformBuffer = this.device.createBuffer({
			usage: Buffer.UNIFORM | Buffer.COPY_DST,
			byteLength
		});
		const uniformBufferData = this.getUniformBufferData(uniformBufferName);
		uniformBuffer.write(uniformBufferData);
		return uniformBuffer;
	}
	/** Returns the managed uniform buffer for the named block. */
	getManagedUniformBuffer(uniformBufferName) {
		if (!this.uniformBuffers.get(uniformBufferName)) {
			const byteLength = this.getUniformBufferByteLength(uniformBufferName);
			const uniformBuffer = this.device.createBuffer({
				usage: Buffer.UNIFORM | Buffer.COPY_DST,
				byteLength
			});
			this.uniformBuffers.set(uniformBufferName, uniformBuffer);
		}
		return this.uniformBuffers.get(uniformBufferName);
	}
	/**
	* Updates every managed uniform buffer whose source uniforms have changed.
	*
	* @returns The first redraw reason encountered, or `false` if nothing changed.
	*/
	updateUniformBuffers() {
		let reason = false;
		for (const uniformBufferName of this.uniformBlocks.keys()) {
			const bufferReason = this.updateUniformBuffer(uniformBufferName);
			reason ||= bufferReason;
		}
		if (reason) log.log(3, `UniformStore.updateUniformBuffers(): ${reason}`)();
		return reason;
	}
	/**
	* Updates one managed uniform buffer if its corresponding block is dirty.
	*
	* @returns The redraw reason for the update, or `false` if no write occurred.
	*/
	updateUniformBuffer(uniformBufferName) {
		const uniformBlock = this.uniformBlocks.get(uniformBufferName);
		let uniformBuffer = this.uniformBuffers.get(uniformBufferName);
		let reason = false;
		if (uniformBuffer && uniformBlock?.needsRedraw) {
			reason ||= uniformBlock.needsRedraw;
			const uniformBufferData = this.getUniformBufferData(uniformBufferName);
			uniformBuffer = this.uniformBuffers.get(uniformBufferName);
			uniformBuffer?.write(uniformBufferData);
			const uniformValues = this.uniformBlocks.get(uniformBufferName)?.getAllUniforms();
			log.log(4, `Writing to uniform buffer ${String(uniformBufferName)}`, uniformBufferData, uniformValues)();
		}
		return reason;
	}
};
/**
* Returns the default uniform-buffer layout for the supplied device.
*/
function getDefaultUniformBufferLayout(device) {
	return device.type === "webgpu" ? "wgsl-uniform" : "std140";
}
//#endregion
//#region node_modules/@deck.gl/core/dist/shaderlib/project/project-functions.js
/**
* Projection utils
* TODO: move to Viewport class?
*/
var DEFAULT_COORDINATE_ORIGIN = [
	0,
	0,
	0
];
function lngLatZToWorldPosition(lngLatZ, viewport, offsetMode = false) {
	const p = viewport.projectPosition(lngLatZ);
	if (offsetMode && viewport instanceof WebMercatorViewport) {
		const [longitude, latitude, z = 0] = lngLatZ;
		p[2] = z * viewport.getDistanceScales([longitude, latitude]).unitsPerMeter[2];
	}
	return p;
}
function normalizeParameters(opts) {
	const { viewport, modelMatrix, coordinateOrigin } = opts;
	let { coordinateSystem, fromCoordinateSystem, fromCoordinateOrigin } = opts;
	if (coordinateSystem === "default") coordinateSystem = viewport.isGeospatial ? "lnglat" : "cartesian";
	if (fromCoordinateSystem === void 0) fromCoordinateSystem = coordinateSystem;
	else if (fromCoordinateSystem === "default") fromCoordinateSystem = viewport.isGeospatial ? "lnglat" : "cartesian";
	if (fromCoordinateOrigin === void 0) fromCoordinateOrigin = coordinateOrigin;
	return {
		viewport,
		coordinateSystem,
		coordinateOrigin,
		modelMatrix,
		fromCoordinateSystem,
		fromCoordinateOrigin
	};
}
/** Get the common space position from world coordinates in the given coordinate system */
function getWorldPosition(position, { viewport, modelMatrix, coordinateSystem, coordinateOrigin, offsetMode }) {
	let [x, y, z = 0] = position;
	if (modelMatrix) [x, y, z] = transformMat4([], [
		x,
		y,
		z,
		1
	], modelMatrix);
	switch (coordinateSystem) {
		case "default": return getWorldPosition(position, {
			viewport,
			modelMatrix,
			coordinateSystem: viewport.isGeospatial ? "lnglat" : "cartesian",
			coordinateOrigin,
			offsetMode
		});
		case "lnglat": return lngLatZToWorldPosition([
			x,
			y,
			z
		], viewport, offsetMode);
		case "lnglat-offsets": return lngLatZToWorldPosition([
			x + coordinateOrigin[0],
			y + coordinateOrigin[1],
			z + (coordinateOrigin[2] || 0)
		], viewport, offsetMode);
		case "meter-offsets": return lngLatZToWorldPosition(addMetersToLngLat(coordinateOrigin, [
			x,
			y,
			z
		]), viewport, offsetMode);
		case "cartesian": return viewport.isGeospatial ? [
			x + coordinateOrigin[0],
			y + coordinateOrigin[1],
			z + coordinateOrigin[2]
		] : viewport.projectPosition([
			x,
			y,
			z
		]);
		default: throw new Error(`Invalid coordinateSystem: ${coordinateSystem}`);
	}
}
/**
* Equivalent to project_position in project.glsl
* projects a user supplied position to world position directly with or without
* a reference coordinate system
*/
function projectPosition(position, params) {
	const { viewport, coordinateSystem, coordinateOrigin, modelMatrix, fromCoordinateSystem, fromCoordinateOrigin } = normalizeParameters(params);
	const { autoOffset = true } = params;
	const { geospatialOrigin = DEFAULT_COORDINATE_ORIGIN, shaderCoordinateOrigin = DEFAULT_COORDINATE_ORIGIN, offsetMode = false } = autoOffset ? getOffsetOrigin(viewport, coordinateSystem, coordinateOrigin) : {};
	const worldPosition = getWorldPosition(position, {
		viewport,
		modelMatrix,
		coordinateSystem: fromCoordinateSystem,
		coordinateOrigin: fromCoordinateOrigin,
		offsetMode
	});
	if (offsetMode) sub(worldPosition, worldPosition, viewport.projectPosition(geospatialOrigin || shaderCoordinateOrigin));
	return worldPosition;
}
//#endregion
//#region node_modules/@luma.gl/engine/dist/utils/uid.js
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
//#region node_modules/@luma.gl/engine/dist/geometry/gpu-geometry.js
var GPUGeometry = class {
	id;
	userData = {};
	/** Determines how vertices are read from the 'vertex' attributes */
	topology;
	bufferLayout = [];
	vertexCount;
	indices;
	attributes;
	constructor(props) {
		this.id = props.id || uid("geometry");
		this.topology = props.topology;
		this.indices = props.indices || null;
		this.attributes = props.attributes;
		this.vertexCount = props.vertexCount;
		this.bufferLayout = props.bufferLayout || [];
		if (this.indices) {
			if (!(this.indices.usage & Buffer.INDEX)) throw new Error("Index buffer must have INDEX usage");
		}
	}
	destroy() {
		this.indices?.destroy();
		for (const attribute of Object.values(this.attributes)) attribute.destroy();
	}
	getVertexCount() {
		return this.vertexCount;
	}
	getAttributes() {
		return this.attributes;
	}
	getIndexes() {
		return this.indices || null;
	}
	_calculateVertexCount(positions) {
		return positions.byteLength / 12;
	}
};
function makeGPUGeometry(device, geometry) {
	if (geometry instanceof GPUGeometry) return geometry;
	const indices = getIndexBufferFromGeometry(device, geometry);
	const { attributes, bufferLayout } = getAttributeBuffersFromGeometry(device, geometry);
	return new GPUGeometry({
		topology: geometry.topology || "triangle-list",
		bufferLayout,
		vertexCount: geometry.vertexCount,
		indices,
		attributes
	});
}
function getIndexBufferFromGeometry(device, geometry) {
	if (!geometry.indices) return;
	const data = geometry.indices.value;
	return device.createBuffer({
		usage: Buffer.INDEX,
		data
	});
}
function getAttributeBuffersFromGeometry(device, geometry) {
	const bufferLayout = [];
	const attributes = {};
	for (const [attributeName, attribute] of Object.entries(geometry.attributes)) {
		let name = attributeName;
		switch (attributeName) {
			case "POSITION":
				name = "positions";
				break;
			case "NORMAL":
				name = "normals";
				break;
			case "TEXCOORD_0":
				name = "texCoords";
				break;
			case "TEXCOORD_1":
				name = "texCoords1";
				break;
			case "COLOR_0":
				name = "colors";
				break;
		}
		if (attribute) {
			attributes[name] = device.createBuffer({
				data: attribute.value,
				id: `${attributeName}-buffer`
			});
			const { value, size, normalized } = attribute;
			if (size === void 0) throw new Error(`Attribute ${attributeName} is missing a size`);
			bufferLayout.push({
				name,
				format: vertexFormatDecoder.getVertexFormatFromAttribute(value, size, normalized)
			});
		}
	}
	return {
		attributes,
		bufferLayout,
		vertexCount: geometry._calculateVertexCount(geometry.attributes, geometry.indices)
	};
}
//#endregion
//#region node_modules/@luma.gl/engine/dist/debug/debug-shader-layout.js
/**
* Extracts a table suitable for `console.table()` from a shader layout to assist in debugging.
* @param layout shader layout
* @param name app should provide the most meaningful name, usually the model or pipeline name / id.
* @returns
*/
function getDebugTableForShaderLayout(layout, name) {
	const table = {};
	const header = "Values";
	if (layout.attributes.length === 0 && !layout.varyings?.length) return { "No attributes or varyings": { [header]: "N/A" } };
	for (const attributeDeclaration of layout.attributes) if (attributeDeclaration) {
		const glslDeclaration = `${attributeDeclaration.location} ${attributeDeclaration.name}: ${attributeDeclaration.type}`;
		table[`in ${glslDeclaration}`] = { [header]: attributeDeclaration.stepMode || "vertex" };
	}
	for (const varyingDeclaration of layout.varyings || []) {
		const glslDeclaration = `${varyingDeclaration.location} ${varyingDeclaration.name}`;
		table[`out ${glslDeclaration}`] = { [header]: JSON.stringify(varyingDeclaration) };
	}
	return table;
}
//#endregion
//#region node_modules/@luma.gl/engine/dist/debug/debug-framebuffer.js
var DEBUG_FRAMEBUFFER_STATE_KEY = "__debugFramebufferState";
var DEFAULT_MARGIN_PX = 8;
/**
* Debug utility to blit queued offscreen framebuffers into the default framebuffer
* without CPU readback. Currently implemented for WebGL only.
*/
function debugFramebuffer(renderPass, source, options) {
	if (renderPass.device.type !== "webgl") return;
	const state = getDebugFramebufferState(renderPass.device);
	if (state.flushing) return;
	if (isDefaultRenderPass(renderPass)) {
		flushDebugFramebuffers(renderPass, options, state);
		return;
	}
	if (source && isFramebuffer(source) && source.handle !== null) {
		if (!state.queuedFramebuffers.includes(source)) state.queuedFramebuffers.push(source);
	}
}
function flushDebugFramebuffers(renderPass, options, state) {
	if (state.queuedFramebuffers.length === 0) return;
	const { gl } = renderPass.device;
	const previousReadFramebuffer = gl.getParameter(36010);
	const previousDrawFramebuffer = gl.getParameter(36006);
	const [targetWidth, targetHeight] = renderPass.device.getDefaultCanvasContext().getDrawingBufferSize();
	let topPx = parseCssPixel(options.top, DEFAULT_MARGIN_PX);
	const leftPx = parseCssPixel(options.left, DEFAULT_MARGIN_PX);
	state.flushing = true;
	try {
		for (const framebuffer of state.queuedFramebuffers) {
			const [targetX0, targetY0, targetX1, targetY1, previewHeight] = getOverlayRect({
				framebuffer,
				targetWidth,
				targetHeight,
				topPx,
				leftPx,
				minimap: options.minimap
			});
			gl.bindFramebuffer(36008, framebuffer.handle);
			gl.bindFramebuffer(36009, null);
			gl.blitFramebuffer(0, 0, framebuffer.width, framebuffer.height, targetX0, targetY0, targetX1, targetY1, 16384, 9728);
			topPx += previewHeight + DEFAULT_MARGIN_PX;
		}
	} finally {
		gl.bindFramebuffer(36008, previousReadFramebuffer);
		gl.bindFramebuffer(36009, previousDrawFramebuffer);
		state.flushing = false;
	}
}
function getOverlayRect(options) {
	const { framebuffer, targetWidth, targetHeight, topPx, leftPx, minimap } = options;
	const maxWidth = minimap ? Math.max(Math.floor(targetWidth / 4), 1) : targetWidth;
	const maxHeight = minimap ? Math.max(Math.floor(targetHeight / 4), 1) : targetHeight;
	const scale = Math.min(maxWidth / framebuffer.width, maxHeight / framebuffer.height);
	const previewWidth = Math.max(Math.floor(framebuffer.width * scale), 1);
	const previewHeight = Math.max(Math.floor(framebuffer.height * scale), 1);
	const targetX0 = leftPx;
	const targetY0 = Math.max(targetHeight - topPx - previewHeight, 0);
	return [
		targetX0,
		targetY0,
		targetX0 + previewWidth,
		targetY0 + previewHeight,
		previewHeight
	];
}
function getDebugFramebufferState(device) {
	device.userData[DEBUG_FRAMEBUFFER_STATE_KEY] ||= {
		flushing: false,
		queuedFramebuffers: []
	};
	return device.userData[DEBUG_FRAMEBUFFER_STATE_KEY];
}
function isFramebuffer(value) {
	return "colorAttachments" in value;
}
function isDefaultRenderPass(renderPass) {
	const framebuffer = renderPass.props.framebuffer;
	return !framebuffer || framebuffer.handle === null;
}
function parseCssPixel(value, defaultValue) {
	if (!value) return defaultValue;
	const parsedValue = Number.parseInt(value, 10);
	return Number.isFinite(parsedValue) ? parsedValue : defaultValue;
}
//#endregion
//#region node_modules/@luma.gl/engine/dist/utils/deep-equal.js
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
//#region node_modules/@luma.gl/engine/dist/utils/buffer-layout-helper.js
/** BufferLayoutHelper is a helper class that should not be used directly by applications */
var BufferLayoutHelper = class {
	bufferLayouts;
	constructor(bufferLayouts) {
		this.bufferLayouts = bufferLayouts;
	}
	getBufferLayout(name) {
		return this.bufferLayouts.find((layout) => layout.name === name) || null;
	}
	/** Get attribute names from a BufferLayout */
	getAttributeNamesForBuffer(bufferLayout) {
		return bufferLayout.attributes ? bufferLayout.attributes?.map((layout) => layout.attribute) : [bufferLayout.name];
	}
	mergeBufferLayouts(bufferLayouts1, bufferLayouts2) {
		const mergedLayouts = [...bufferLayouts1];
		for (const attribute of bufferLayouts2) {
			const index = mergedLayouts.findIndex((attribute2) => attribute2.name === attribute.name);
			if (index < 0) mergedLayouts.push(attribute);
			else mergedLayouts[index] = attribute;
		}
		return mergedLayouts;
	}
	getBufferIndex(bufferName) {
		const bufferIndex = this.bufferLayouts.findIndex((layout) => layout.name === bufferName);
		if (bufferIndex === -1) log.warn(`BufferLayout: Missing buffer for "${bufferName}".`)();
		return bufferIndex;
	}
};
//#endregion
//#region node_modules/@luma.gl/engine/dist/utils/buffer-layout-order.js
function getMinLocation(attributeNames, shaderLayoutMap) {
	let minLocation = Infinity;
	for (const name of attributeNames) {
		const location = shaderLayoutMap[name];
		if (location !== void 0) minLocation = Math.min(minLocation, location);
	}
	return minLocation;
}
function sortedBufferLayoutByShaderSourceLocations(shaderLayout, bufferLayout) {
	const shaderLayoutMap = Object.fromEntries(shaderLayout.attributes.map((attr) => [attr.name, attr.location]));
	const sortedLayout = bufferLayout.slice();
	sortedLayout.sort((a, b) => {
		const attributeNamesA = a.attributes ? a.attributes.map((attr) => attr.attribute) : [a.name];
		const attributeNamesB = b.attributes ? b.attributes.map((attr) => attr.attribute) : [b.name];
		return getMinLocation(attributeNamesA, shaderLayoutMap) - getMinLocation(attributeNamesB, shaderLayoutMap);
	});
	return sortedLayout;
}
//#endregion
//#region node_modules/@luma.gl/engine/dist/utils/shader-module-utils.js
function mergeShaderModuleBindingsIntoLayout(shaderLayout, modules) {
	if (!shaderLayout || !modules.some((module) => module.bindingLayout?.length)) return shaderLayout;
	const mergedLayout = {
		...shaderLayout,
		bindings: shaderLayout.bindings.map((binding) => ({ ...binding }))
	};
	if ("attributes" in (shaderLayout || {})) mergedLayout.attributes = shaderLayout?.attributes || [];
	for (const module of modules) for (const bindingLayout of module.bindingLayout || []) for (const relatedBindingName of getRelatedBindingNames(bindingLayout.name)) {
		const binding = mergedLayout.bindings.find((candidate) => candidate.name === relatedBindingName);
		if (binding?.group === 0) binding.group = bindingLayout.group;
	}
	return mergedLayout;
}
function shaderModuleHasUniforms(module) {
	return Boolean(module.uniformTypes && !isObjectEmpty(module.uniformTypes));
}
/** Returns binding-name aliases that should share the module-declared bind group. */
function getRelatedBindingNames(bindingName) {
	const bindingNames = new Set([bindingName, `${bindingName}Uniforms`]);
	if (!bindingName.endsWith("Uniforms")) bindingNames.add(`${bindingName}Sampler`);
	return [...bindingNames];
}
function isObjectEmpty(obj) {
	for (const key in obj) return false;
	return true;
}
//#endregion
//#region node_modules/@luma.gl/engine/dist/model/split-uniforms-and-bindings.js
function isUniformValue(value) {
	return isNumericArray(value) || typeof value === "number" || typeof value === "boolean";
}
function splitUniformsAndBindings(uniforms, uniformTypes = {}) {
	const result = {
		bindings: {},
		uniforms: {}
	};
	Object.keys(uniforms).forEach((name) => {
		const uniform = uniforms[name];
		if (Object.prototype.hasOwnProperty.call(uniformTypes, name) || isUniformValue(uniform)) result.uniforms[name] = uniform;
		else result.bindings[name] = uniform;
	});
	return result;
}
//#endregion
//#region node_modules/@luma.gl/engine/dist/shader-inputs.js
/**
* ShaderInputs holds uniform and binding values for one or more shader modules,
* - It can generate binary data for any uniform buffer
* - It can manage a uniform buffer for each block
* - It can update managed uniform buffers with a single call
* - It performs some book keeping on what has changed to minimize unnecessary writes to uniform buffers.
*/
var ShaderInputs = class {
	options = { disableWarnings: false };
	/**
	* The map of modules
	* @todo should should this include the resolved dependencies?
	*/
	modules;
	/** Stores the uniform values for each module */
	moduleUniforms;
	/** Stores the uniform bindings for each module  */
	moduleBindings;
	/** Tracks if uniforms have changed */
	/**
	* Create a new UniformStore instance
	* @param modules
	*/
	constructor(modules, options) {
		Object.assign(this.options, options);
		const resolvedModules = getShaderModuleDependencies(Object.values(modules).filter(isShaderInputsModuleWithDependencies));
		for (const resolvedModule of resolvedModules) modules[resolvedModule.name] = resolvedModule;
		log.log(1, "Creating ShaderInputs with modules", Object.keys(modules))();
		this.modules = modules;
		this.moduleUniforms = {};
		this.moduleBindings = {};
		for (const [name, module] of Object.entries(modules)) if (module) {
			this._addModule(module);
			if (module.name && name !== module.name && !this.options.disableWarnings) log.warn(`Module name: ${name} vs ${module.name}`)();
		}
	}
	/** Destroy */
	destroy() {}
	/**
	* Set module props
	*/
	setProps(props) {
		for (const name of Object.keys(props)) {
			const moduleName = name;
			const moduleProps = props[moduleName] || {};
			const module = this.modules[moduleName];
			if (!module) {
				if (!this.options.disableWarnings) log.warn(`Module ${name} not found`)();
			} else {
				const oldUniforms = this.moduleUniforms[moduleName];
				const oldBindings = this.moduleBindings[moduleName];
				const { uniforms, bindings } = splitUniformsAndBindings(module.getUniforms?.(moduleProps, oldUniforms) || moduleProps, module.uniformTypes);
				this.moduleUniforms[moduleName] = mergeModuleUniforms(oldUniforms, uniforms, module.uniformTypes);
				this.moduleBindings[moduleName] = {
					...oldBindings,
					...bindings
				};
			}
		}
	}
	/**
	* Return the map of modules
	* @todo should should this include the resolved dependencies?
	*/
	getModules() {
		return Object.values(this.modules);
	}
	/** Get all uniform values for all modules */
	getUniformValues() {
		return this.moduleUniforms;
	}
	/** Merges all bindings for the shader (from the various modules) */
	getBindingValues() {
		const bindings = {};
		for (const moduleBindings of Object.values(this.moduleBindings)) Object.assign(bindings, moduleBindings);
		return bindings;
	}
	/** Return a debug table that can be used for console.table() or log.table() */
	getDebugTable() {
		const table = {};
		for (const [moduleName, module] of Object.entries(this.moduleUniforms)) for (const [key, value] of Object.entries(module)) table[`${moduleName}.${key}`] = {
			type: this.modules[moduleName].uniformTypes?.[key],
			value: String(value)
		};
		return table;
	}
	_addModule(module) {
		const moduleName = module.name;
		this.moduleUniforms[moduleName] = mergeModuleUniforms({}, module.defaultUniforms || {}, module.uniformTypes);
		this.moduleBindings[moduleName] = {};
	}
};
function mergeModuleUniforms(currentUniforms = {}, nextUniforms = {}, uniformTypes = {}) {
	const mergedUniforms = { ...currentUniforms };
	for (const [key, value] of Object.entries(nextUniforms)) if (value !== void 0) mergedUniforms[key] = mergeModuleUniformValue(currentUniforms[key], value, uniformTypes[key]);
	return mergedUniforms;
}
function mergeModuleUniformValue(currentValue, nextValue, uniformType) {
	if (!uniformType || typeof uniformType === "string") return cloneModuleUniformValue(nextValue);
	if (Array.isArray(uniformType)) {
		if (isPackedUniformArrayValue(nextValue) || !Array.isArray(nextValue)) return cloneModuleUniformValue(nextValue);
		const currentArray = Array.isArray(currentValue) && !isPackedUniformArrayValue(currentValue) ? [...currentValue] : [];
		const mergedArray = currentArray.slice();
		for (let index = 0; index < nextValue.length; index++) {
			const elementValue = nextValue[index];
			if (elementValue !== void 0) mergedArray[index] = mergeModuleUniformValue(currentArray[index], elementValue, uniformType[0]);
		}
		return mergedArray;
	}
	if (!isPlainUniformObject(nextValue)) return cloneModuleUniformValue(nextValue);
	const uniformStruct = uniformType;
	const currentObject = isPlainUniformObject(currentValue) ? currentValue : {};
	const mergedObject = { ...currentObject };
	for (const [key, value] of Object.entries(nextValue)) if (value !== void 0) mergedObject[key] = mergeModuleUniformValue(currentObject[key], value, uniformStruct[key]);
	return mergedObject;
}
function cloneModuleUniformValue(value) {
	if (ArrayBuffer.isView(value)) return Array.prototype.slice.call(value);
	if (Array.isArray(value)) {
		if (isPackedUniformArrayValue(value)) return value.slice();
		return value.map((element) => element === void 0 ? void 0 : cloneModuleUniformValue(element));
	}
	if (isPlainUniformObject(value)) return Object.fromEntries(Object.entries(value).map(([key, nestedValue]) => [key, nestedValue === void 0 ? void 0 : cloneModuleUniformValue(nestedValue)]));
	return value;
}
function isPackedUniformArrayValue(value) {
	return ArrayBuffer.isView(value) || Array.isArray(value) && (value.length === 0 || typeof value[0] === "number");
}
function isPlainUniformObject(value) {
	return Boolean(value) && typeof value === "object" && !Array.isArray(value) && !ArrayBuffer.isView(value);
}
function isShaderInputsModuleWithDependencies(module) {
	return Boolean(module?.dependencies);
}
//#endregion
//#region node_modules/@luma.gl/engine/dist/dynamic-texture/texture-data.js
/** Map of cube texture face names to face indexes */
var TEXTURE_CUBE_FACE_MAP = {
	"+X": 0,
	"-X": 1,
	"+Y": 2,
	"-Y": 3,
	"+Z": 4,
	"-Z": 5
};
function getFirstMipLevel(layer) {
	if (!layer) return null;
	return Array.isArray(layer) ? layer[0] ?? null : layer;
}
function getTextureSizeFromData(props) {
	const { dimension, data } = props;
	if (!data) return null;
	switch (dimension) {
		case "1d": {
			const mipLevel = getFirstMipLevel(data);
			if (!mipLevel) return null;
			const { width } = getTextureMipLevelSize(mipLevel);
			return {
				width,
				height: 1
			};
		}
		case "2d": {
			const mipLevel = getFirstMipLevel(data);
			return mipLevel ? getTextureMipLevelSize(mipLevel) : null;
		}
		case "3d":
		case "2d-array": {
			if (!Array.isArray(data) || data.length === 0) return null;
			const mipLevel = getFirstMipLevel(data[0]);
			return mipLevel ? getTextureMipLevelSize(mipLevel) : null;
		}
		case "cube": {
			const face = Object.keys(data)[0] ?? null;
			if (!face) return null;
			const faceData = data[face];
			const mipLevel = getFirstMipLevel(faceData);
			return mipLevel ? getTextureMipLevelSize(mipLevel) : null;
		}
		case "cube-array": {
			if (!Array.isArray(data) || data.length === 0) return null;
			const firstCube = data[0];
			const face = Object.keys(firstCube)[0] ?? null;
			if (!face) return null;
			const mipLevel = getFirstMipLevel(firstCube[face]);
			return mipLevel ? getTextureMipLevelSize(mipLevel) : null;
		}
		default: return null;
	}
}
function getTextureMipLevelSize(data) {
	if (isExternalImage(data)) return getExternalImageSize(data);
	if (typeof data === "object" && "width" in data && "height" in data) return {
		width: data.width,
		height: data.height
	};
	throw new Error("Unsupported mip-level data");
}
/** Type guard: is a mip-level `TextureImageData` (vs ExternalImage or bare typed array) */
function isTextureImageData(data) {
	return typeof data === "object" && data !== null && "data" in data && "width" in data && "height" in data;
}
function isTypedArrayMipLevelData(data) {
	return ArrayBuffer.isView(data);
}
function resolveTextureImageFormat(data) {
	const { textureFormat, format } = data;
	if (textureFormat && format && textureFormat !== format) throw new Error(`Conflicting texture formats "${textureFormat}" and "${format}" provided for the same mip level`);
	return textureFormat ?? format;
}
/** Resolve size for a single mip-level datum */
/** Convert cube face label to depth index */
function getCubeFaceIndex(face) {
	const idx = TEXTURE_CUBE_FACE_MAP[face];
	if (idx === void 0) throw new Error(`Invalid cube face: ${face}`);
	return idx;
}
/** Convert cube face label to texture slice index. Index can be used with `setTexture2DData()`. */
function getCubeArrayFaceIndex(cubeIndex, face) {
	return 6 * cubeIndex + getCubeFaceIndex(face);
}
/** Experimental: Set multiple mip levels (1D) */
function getTexture1DSubresources(data) {
	throw new Error("setTexture1DData not supported in WebGL.");
}
/** Normalize 2D layer payload into an array of mip-level items */
function _normalizeTexture2DData(data) {
	return Array.isArray(data) ? data : [data];
}
/** Experimental: Set multiple mip levels (2D), optionally at `z` (depth/array index) */
function getTexture2DSubresources(slice, lodData, baseLevelSize, textureFormat) {
	const lodArray = _normalizeTexture2DData(lodData);
	const z = slice;
	const subresources = [];
	for (let mipLevel = 0; mipLevel < lodArray.length; mipLevel++) {
		const imageData = lodArray[mipLevel];
		if (isExternalImage(imageData)) subresources.push({
			type: "external-image",
			image: imageData,
			z,
			mipLevel
		});
		else if (isTextureImageData(imageData)) subresources.push({
			type: "texture-data",
			data: imageData,
			textureFormat: resolveTextureImageFormat(imageData),
			z,
			mipLevel
		});
		else if (isTypedArrayMipLevelData(imageData) && baseLevelSize) subresources.push({
			type: "texture-data",
			data: {
				data: imageData,
				width: Math.max(1, baseLevelSize.width >> mipLevel),
				height: Math.max(1, baseLevelSize.height >> mipLevel),
				...textureFormat ? { format: textureFormat } : {}
			},
			textureFormat,
			z,
			mipLevel
		});
		else throw new Error("Unsupported 2D mip-level payload");
	}
	return subresources;
}
/** 3D: multiple depth slices, each may carry multiple mip levels */
function getTexture3DSubresources(data) {
	const subresources = [];
	for (let depth = 0; depth < data.length; depth++) subresources.push(...getTexture2DSubresources(depth, data[depth]));
	return subresources;
}
/** 2D array: multiple layers, each may carry multiple mip levels */
function getTextureArraySubresources(data) {
	const subresources = [];
	for (let layer = 0; layer < data.length; layer++) subresources.push(...getTexture2DSubresources(layer, data[layer]));
	return subresources;
}
/** Cube: 6 faces, each may carry multiple mip levels */
function getTextureCubeSubresources(data) {
	const subresources = [];
	for (const [face, faceData] of Object.entries(data)) {
		const faceDepth = getCubeFaceIndex(face);
		subresources.push(...getTexture2DSubresources(faceDepth, faceData));
	}
	return subresources;
}
/** Cube array: multiple cubes (faces×layers), each face may carry multiple mips */
function getTextureCubeArraySubresources(data) {
	const subresources = [];
	data.forEach((cubeData, cubeIndex) => {
		for (const [face, faceData] of Object.entries(cubeData)) {
			const faceDepth = getCubeArrayFaceIndex(cubeIndex, face);
			subresources.push(...getTexture2DSubresources(faceDepth, faceData));
		}
	});
	return subresources;
}
//#endregion
//#region node_modules/@luma.gl/engine/dist/dynamic-texture/dynamic-texture.js
/**
* Dynamic Textures
*
* - Mipmaps - DynamicTexture can generate mipmaps for textures (WebGPU does not provide built-in mipmap generation).
*
* - Texture initialization and updates - complex textures (2d array textures, cube textures, 3d textures) need multiple images
*   `DynamicTexture` provides an API that makes it easy to provide the required data.
*
* - Texture resizing - Textures are immutable in WebGPU, meaning that they cannot be resized after creation.
*   DynamicTexture provides a `resize()` method that internally creates a new texture with the same parameters
*   but a different size.
*
* - Async image data initialization - It is often very convenient to be able to initialize textures with promises
*   returned by image or data loading functions, as it allows a callback-free linear style of programming.
*
* @note GPU Textures are quite complex objects, with many subresources and modes of usage.
* The `DynamicTexture` class allows luma.gl to provide some support for working with textures
* without accumulating excessive complexity in the core Texture class which is designed as an immutable nature of GPU resource.
*/
var DynamicTexture = class DynamicTexture {
	device;
	id;
	/** Props with defaults resolved (except `data` which is processed separately) */
	props;
	/** Created resources */
	_texture = null;
	_sampler = null;
	_view = null;
	/** Ready when GPU texture has been created and data (if any) uploaded */
	ready;
	isReady = false;
	destroyed = false;
	resolveReady = () => {};
	rejectReady = () => {};
	get texture() {
		if (!this._texture) throw new Error("Texture not initialized yet");
		return this._texture;
	}
	get sampler() {
		if (!this._sampler) throw new Error("Sampler not initialized yet");
		return this._sampler;
	}
	get view() {
		if (!this._view) throw new Error("View not initialized yet");
		return this._view;
	}
	get [Symbol.toStringTag]() {
		return "DynamicTexture";
	}
	toString() {
		const width = this._texture?.width ?? this.props.width ?? "?";
		const height = this._texture?.height ?? this.props.height ?? "?";
		return `DynamicTexture:"${this.id}":${width}x${height}px:(${this.isReady ? "ready" : "loading..."})`;
	}
	constructor(device, props) {
		this.device = device;
		const id = uid("dynamic-texture");
		const originalPropsWithAsyncData = props;
		this.props = {
			...DynamicTexture.defaultProps,
			id,
			...props,
			data: null
		};
		this.id = this.props.id;
		this.ready = new Promise((resolve, reject) => {
			this.resolveReady = resolve;
			this.rejectReady = reject;
		});
		this.initAsync(originalPropsWithAsyncData);
	}
	/** @note Fire and forget; caller can await `ready` */
	async initAsync(originalPropsWithAsyncData) {
		try {
			const propsWithSyncData = await this._loadAllData(originalPropsWithAsyncData);
			this._checkNotDestroyed();
			const subresources = propsWithSyncData.data ? getTextureSubresources({
				...propsWithSyncData,
				width: originalPropsWithAsyncData.width,
				height: originalPropsWithAsyncData.height,
				format: originalPropsWithAsyncData.format
			}) : [];
			const userProvidedFormat = "format" in originalPropsWithAsyncData && originalPropsWithAsyncData.format !== void 0;
			const userProvidedUsage = "usage" in originalPropsWithAsyncData && originalPropsWithAsyncData.usage !== void 0;
			const deduceSize = () => {
				if (this.props.width && this.props.height) return {
					width: this.props.width,
					height: this.props.height
				};
				const size = getTextureSizeFromData(propsWithSyncData);
				if (size) return size;
				return {
					width: this.props.width || 1,
					height: this.props.height || 1
				};
			};
			const size = deduceSize();
			if (!size || size.width <= 0 || size.height <= 0) throw new Error(`${this} size could not be determined or was zero`);
			const textureData = analyzeTextureSubresources(this.device, subresources, size, { format: userProvidedFormat ? originalPropsWithAsyncData.format : void 0 });
			const resolvedFormat = textureData.format ?? this.props.format;
			const baseTextureProps = {
				...this.props,
				...size,
				format: resolvedFormat,
				mipLevels: 1,
				data: void 0
			};
			if (this.device.isTextureFormatCompressed(resolvedFormat) && !userProvidedUsage) baseTextureProps.usage = Texture.SAMPLE | Texture.COPY_DST;
			const shouldGenerateMipmaps = this.props.mipmaps && !textureData.hasExplicitMipChain && !this.device.isTextureFormatCompressed(resolvedFormat);
			if (this.device.type === "webgpu" && shouldGenerateMipmaps) {
				const requiredUsage = this.props.dimension === "3d" ? Texture.SAMPLE | Texture.STORAGE | Texture.COPY_DST | Texture.COPY_SRC : Texture.SAMPLE | Texture.RENDER | Texture.COPY_DST | Texture.COPY_SRC;
				baseTextureProps.usage |= requiredUsage;
			}
			const maxMips = this.device.getMipLevelCount(baseTextureProps.width, baseTextureProps.height);
			const desired = textureData.hasExplicitMipChain ? textureData.mipLevels : this.props.mipLevels === "auto" ? maxMips : Math.max(1, Math.min(maxMips, this.props.mipLevels ?? 1));
			const finalTextureProps = {
				...baseTextureProps,
				mipLevels: desired
			};
			this._texture = this.device.createTexture(finalTextureProps);
			this._sampler = this.texture.sampler;
			this._view = this.texture.view;
			if (textureData.subresources.length) this._setTextureSubresources(textureData.subresources);
			if (this.props.mipmaps && !textureData.hasExplicitMipChain && !shouldGenerateMipmaps) log.warn(`${this} skipping auto-generated mipmaps for compressed texture format`)();
			if (shouldGenerateMipmaps) this.generateMipmaps();
			this.isReady = true;
			this.resolveReady(this.texture);
			log.info(0, `${this} created`)();
		} catch (e) {
			const err = e instanceof Error ? e : new Error(String(e));
			this.rejectReady(err);
		}
	}
	destroy() {
		if (this._texture) {
			this._texture.destroy();
			this._texture = null;
			this._sampler = null;
			this._view = null;
		}
		this.destroyed = true;
	}
	generateMipmaps() {
		if (this.device.type === "webgl") this.texture.generateMipmapsWebGL();
		else if (this.device.type === "webgpu") this.device.generateMipmapsWebGPU(this.texture);
		else log.warn(`${this} mipmaps not supported on ${this.device.type}`);
	}
	/** Set sampler or create one from props */
	setSampler(sampler = {}) {
		this._checkReady();
		const s = sampler instanceof Sampler ? sampler : this.device.createSampler(sampler);
		this.texture.setSampler(s);
		this._sampler = s;
	}
	/**
	* Copies texture contents into a GPU buffer and waits until the copy is complete.
	* The caller owns the returned buffer and must destroy it when finished.
	*/
	async readBuffer(options = {}) {
		if (!this.isReady) await this.ready;
		const width = options.width ?? this.texture.width;
		const height = options.height ?? this.texture.height;
		const depthOrArrayLayers = options.depthOrArrayLayers ?? this.texture.depth;
		const layout = this.texture.computeMemoryLayout({
			width,
			height,
			depthOrArrayLayers
		});
		const buffer = this.device.createBuffer({
			byteLength: layout.byteLength,
			usage: Buffer.COPY_DST | Buffer.MAP_READ
		});
		this.texture.readBuffer({
			...options,
			width,
			height,
			depthOrArrayLayers
		}, buffer);
		const fence = this.device.createFence();
		await fence.signaled;
		fence.destroy();
		return buffer;
	}
	/** Reads texture contents back to CPU memory. */
	async readAsync(options = {}) {
		if (!this.isReady) await this.ready;
		const width = options.width ?? this.texture.width;
		const height = options.height ?? this.texture.height;
		const depthOrArrayLayers = options.depthOrArrayLayers ?? this.texture.depth;
		const layout = this.texture.computeMemoryLayout({
			width,
			height,
			depthOrArrayLayers
		});
		const buffer = await this.readBuffer(options);
		const data = await buffer.readAsync(0, layout.byteLength);
		buffer.destroy();
		return data.buffer;
	}
	/**
	* Resize by cloning the underlying immutable texture.
	* Does not copy contents; caller may need to re-upload and/or regenerate mips.
	*/
	resize(size) {
		this._checkReady();
		if (size.width === this.texture.width && size.height === this.texture.height) return false;
		const prev = this.texture;
		this._texture = prev.clone(size);
		this._sampler = this.texture.sampler;
		this._view = this.texture.view;
		prev.destroy();
		log.info(`${this} resized`);
		return true;
	}
	/** Convert cube face label to texture slice index. Index can be used with `setTexture2DData()`. */
	getCubeFaceIndex(face) {
		const index = TEXTURE_CUBE_FACE_MAP[face];
		if (index === void 0) throw new Error(`Invalid cube face: ${face}`);
		return index;
	}
	/** Convert cube face label to texture slice index. Index can be used with `setTexture2DData()`. */
	getCubeArrayFaceIndex(cubeIndex, face) {
		return 6 * cubeIndex + this.getCubeFaceIndex(face);
	}
	/** @note experimental: Set multiple mip levels (1D) */
	setTexture1DData(data) {
		this._checkReady();
		if (this.texture.props.dimension !== "1d") throw new Error(`${this} is not 1d`);
		const subresources = getTexture1DSubresources(data);
		this._setTextureSubresources(subresources);
	}
	/** @note experimental: Set multiple mip levels (2D), optionally at `z`, slice (depth/array level) index */
	setTexture2DData(lodData, z = 0) {
		this._checkReady();
		if (this.texture.props.dimension !== "2d") throw new Error(`${this} is not 2d`);
		const subresources = getTexture2DSubresources(z, lodData);
		this._setTextureSubresources(subresources);
	}
	/** 3D: multiple depth slices, each may carry multiple mip levels */
	setTexture3DData(data) {
		if (this.texture.props.dimension !== "3d") throw new Error(`${this} is not 3d`);
		const subresources = getTexture3DSubresources(data);
		this._setTextureSubresources(subresources);
	}
	/** 2D array: multiple layers, each may carry multiple mip levels */
	setTextureArrayData(data) {
		if (this.texture.props.dimension !== "2d-array") throw new Error(`${this} is not 2d-array`);
		const subresources = getTextureArraySubresources(data);
		this._setTextureSubresources(subresources);
	}
	/** Cube: 6 faces, each may carry multiple mip levels */
	setTextureCubeData(data) {
		if (this.texture.props.dimension !== "cube") throw new Error(`${this} is not cube`);
		const subresources = getTextureCubeSubresources(data);
		this._setTextureSubresources(subresources);
	}
	/** Cube array: multiple cubes (faces×layers), each face may carry multiple mips */
	setTextureCubeArrayData(data) {
		if (this.texture.props.dimension !== "cube-array") throw new Error(`${this} is not cube-array`);
		const subresources = getTextureCubeArraySubresources(data);
		this._setTextureSubresources(subresources);
	}
	/** Sets multiple mip levels on different `z` slices (depth/array index) */
	_setTextureSubresources(subresources) {
		for (const subresource of subresources) {
			const { z, mipLevel } = subresource;
			switch (subresource.type) {
				case "external-image":
					const { image, flipY } = subresource;
					this.texture.copyExternalImage({
						image,
						z,
						mipLevel,
						flipY
					});
					break;
				case "texture-data":
					const { data, textureFormat } = subresource;
					if (textureFormat && textureFormat !== this.texture.format) throw new Error(`${this} mip level ${mipLevel} uses format "${textureFormat}" but texture format is "${this.texture.format}"`);
					this.texture.writeData(data.data, {
						x: 0,
						y: 0,
						z,
						width: data.width,
						height: data.height,
						depthOrArrayLayers: 1,
						mipLevel
					});
					break;
				default: throw new Error("Unsupported 2D mip-level payload");
			}
		}
	}
	/** Recursively resolve all promises in data structures */
	async _loadAllData(props) {
		const syncData = await awaitAllPromises(props.data);
		return {
			dimension: props.dimension ?? "2d",
			data: syncData ?? null
		};
	}
	_checkNotDestroyed() {
		if (this.destroyed) log.warn(`${this} already destroyed`);
	}
	_checkReady() {
		if (!this.isReady) log.warn(`${this} Cannot perform this operation before ready`);
	}
	static defaultProps = {
		...Texture.defaultProps,
		dimension: "2d",
		data: null,
		mipmaps: false
	};
};
function getTextureSubresources(props) {
	if (!props.data) return [];
	const baseLevelSize = props.width && props.height ? {
		width: props.width,
		height: props.height
	} : void 0;
	const textureFormat = "format" in props ? props.format : void 0;
	switch (props.dimension) {
		case "1d": return getTexture1DSubresources(props.data);
		case "2d": return getTexture2DSubresources(0, props.data, baseLevelSize, textureFormat);
		case "3d": return getTexture3DSubresources(props.data);
		case "2d-array": return getTextureArraySubresources(props.data);
		case "cube": return getTextureCubeSubresources(props.data);
		case "cube-array": return getTextureCubeArraySubresources(props.data);
		default: throw new Error(`Unhandled dimension ${props.dimension}`);
	}
}
function analyzeTextureSubresources(device, subresources, size, options) {
	if (subresources.length === 0) return {
		subresources,
		mipLevels: 1,
		format: options.format,
		hasExplicitMipChain: false
	};
	const groupedSubresources = /* @__PURE__ */ new Map();
	for (const subresource of subresources) {
		const group = groupedSubresources.get(subresource.z) ?? [];
		group.push(subresource);
		groupedSubresources.set(subresource.z, group);
	}
	const hasExplicitMipChain = subresources.some((subresource) => subresource.mipLevel > 0);
	let resolvedFormat = options.format;
	let resolvedMipLevels = Number.POSITIVE_INFINITY;
	const validSubresources = [];
	for (const [z, sliceSubresources] of groupedSubresources) {
		const sortedSubresources = [...sliceSubresources].sort((left, right) => left.mipLevel - right.mipLevel);
		const baseLevel = sortedSubresources[0];
		if (!baseLevel || baseLevel.mipLevel !== 0) throw new Error(`DynamicTexture: slice ${z} is missing mip level 0`);
		const baseSize = getTextureSubresourceSize(device, baseLevel);
		if (baseSize.width !== size.width || baseSize.height !== size.height) throw new Error(`DynamicTexture: slice ${z} base level dimensions ${baseSize.width}x${baseSize.height} do not match expected ${size.width}x${size.height}`);
		const baseFormat = getTextureSubresourceFormat(baseLevel);
		if (baseFormat) {
			if (resolvedFormat && resolvedFormat !== baseFormat) throw new Error(`DynamicTexture: slice ${z} base level format "${baseFormat}" does not match texture format "${resolvedFormat}"`);
			resolvedFormat = baseFormat;
		}
		const mipLevelLimit = resolvedFormat && device.isTextureFormatCompressed(resolvedFormat) ? getMaxCompressedMipLevels(device, baseSize.width, baseSize.height, resolvedFormat) : device.getMipLevelCount(baseSize.width, baseSize.height);
		let validMipLevelsForSlice = 0;
		for (let expectedMipLevel = 0; expectedMipLevel < sortedSubresources.length; expectedMipLevel++) {
			const subresource = sortedSubresources[expectedMipLevel];
			if (!subresource || subresource.mipLevel !== expectedMipLevel) break;
			if (expectedMipLevel >= mipLevelLimit) break;
			const subresourceSize = getTextureSubresourceSize(device, subresource);
			const expectedWidth = Math.max(1, baseSize.width >> expectedMipLevel);
			const expectedHeight = Math.max(1, baseSize.height >> expectedMipLevel);
			if (subresourceSize.width !== expectedWidth || subresourceSize.height !== expectedHeight) break;
			const subresourceFormat = getTextureSubresourceFormat(subresource);
			if (subresourceFormat) {
				if (!resolvedFormat) resolvedFormat = subresourceFormat;
				if (subresourceFormat !== resolvedFormat) break;
			}
			validMipLevelsForSlice++;
			validSubresources.push(subresource);
		}
		resolvedMipLevels = Math.min(resolvedMipLevels, validMipLevelsForSlice);
	}
	const mipLevels = Number.isFinite(resolvedMipLevels) ? Math.max(1, resolvedMipLevels) : 1;
	return {
		subresources: validSubresources.filter((subresource) => subresource.mipLevel < mipLevels),
		mipLevels,
		format: resolvedFormat,
		hasExplicitMipChain
	};
}
function getTextureSubresourceFormat(subresource) {
	if (subresource.type !== "texture-data") return;
	return subresource.textureFormat ?? resolveTextureImageFormat(subresource.data);
}
function getTextureSubresourceSize(device, subresource) {
	switch (subresource.type) {
		case "external-image": return device.getExternalImageSize(subresource.image);
		case "texture-data": return {
			width: subresource.data.width,
			height: subresource.data.height
		};
		default: throw new Error("Unsupported texture subresource");
	}
}
function getMaxCompressedMipLevels(device, baseWidth, baseHeight, format) {
	const { blockWidth = 1, blockHeight = 1 } = device.getTextureFormatInfo(format);
	let mipLevels = 1;
	for (let mipLevel = 1;; mipLevel++) {
		const width = Math.max(1, baseWidth >> mipLevel);
		const height = Math.max(1, baseHeight >> mipLevel);
		if (width < blockWidth || height < blockHeight) break;
		mipLevels++;
	}
	return mipLevels;
}
/** Resolve all promises in a nested data structure */
async function awaitAllPromises(x) {
	x = await x;
	if (Array.isArray(x)) return await Promise.all(x.map(awaitAllPromises));
	if (x && typeof x === "object" && x.constructor === Object) {
		const object = x;
		const values = await Promise.all(Object.values(object).map(awaitAllPromises));
		const keys = Object.keys(object);
		const resolvedObject = {};
		for (let i = 0; i < keys.length; i++) resolvedObject[keys[i]] = values[i];
		return resolvedObject;
	}
	return x;
}
//#endregion
//#region node_modules/@luma.gl/engine/dist/model/model.js
var LOG_DRAW_PRIORITY = 2;
var LOG_DRAW_TIMEOUT = 1e4;
var PIPELINE_INITIALIZATION_FAILED = "render pipeline initialization failed";
/**
* High level draw API for luma.gl.
*
* A `Model` encapsulates shaders, geometry attributes, bindings and render
* pipeline state into a single object. It automatically reuses and rebuilds
* pipelines as render parameters change and exposes convenient hooks for
* updating uniforms and attributes.
*
* Features:
* - Reuses and lazily recompiles {@link RenderPipeline | pipelines} as needed.
* - Integrates with `@luma.gl/shadertools` to assemble GLSL or WGSL from shader modules.
* - Manages geometry attributes and buffer bindings.
* - Accepts textures, samplers and uniform buffers as bindings, including `DynamicTexture`.
* - Provides detailed debug logging and optional shader source inspection.
*/
var Model = class Model {
	static defaultProps = {
		...RenderPipeline.defaultProps,
		source: void 0,
		vs: null,
		fs: null,
		id: "unnamed",
		handle: void 0,
		userData: {},
		defines: {},
		modules: [],
		geometry: null,
		indexBuffer: null,
		attributes: {},
		constantAttributes: {},
		bindings: {},
		uniforms: {},
		varyings: [],
		isInstanced: void 0,
		instanceCount: 0,
		vertexCount: 0,
		shaderInputs: void 0,
		material: void 0,
		pipelineFactory: void 0,
		shaderFactory: void 0,
		transformFeedback: void 0,
		shaderAssembler: ShaderAssembler.getDefaultShaderAssembler(),
		debugShaders: void 0,
		disableWarnings: void 0
	};
	/** Device that created this model */
	device;
	/** Application provided identifier */
	id;
	/** WGSL shader source when using unified shader */
	source;
	/** GLSL vertex shader source */
	vs;
	/** GLSL fragment shader source */
	fs;
	/** Factory used to create render pipelines */
	pipelineFactory;
	/** Factory used to create shaders */
	shaderFactory;
	/** User-supplied per-model data */
	userData = {};
	/** The render pipeline GPU parameters, depth testing etc */
	parameters;
	/** The primitive topology */
	topology;
	/** Buffer layout */
	bufferLayout;
	/** Use instanced rendering */
	isInstanced = void 0;
	/** instance count. `undefined` means not instanced */
	instanceCount = 0;
	/** Vertex count */
	vertexCount;
	/** Index buffer */
	indexBuffer = null;
	/** Buffer-valued attributes */
	bufferAttributes = {};
	/** Constant-valued attributes */
	constantAttributes = {};
	/** Bindings (textures, samplers, uniform buffers) */
	bindings = {};
	/**
	* VertexArray
	* @note not implemented: if bufferLayout is updated, vertex array has to be rebuilt!
	* @todo - allow application to define multiple vertex arrays?
	* */
	vertexArray;
	/** TransformFeedback, WebGL 2 only. */
	transformFeedback = null;
	/** The underlying GPU "program". @note May be recreated if parameters change */
	pipeline;
	/** ShaderInputs instance */
	shaderInputs;
	material = null;
	_uniformStore;
	_attributeInfos = {};
	_gpuGeometry = null;
	props;
	_pipelineNeedsUpdate = "newly created";
	_needsRedraw = "initializing";
	_destroyed = false;
	/** "Time" of last draw. Monotonically increasing timestamp */
	_lastDrawTimestamp = -1;
	_bindingTable = [];
	get [Symbol.toStringTag]() {
		return "Model";
	}
	toString() {
		return `Model(${this.id})`;
	}
	constructor(device, props) {
		this.props = {
			...Model.defaultProps,
			...props
		};
		props = this.props;
		this.id = props.id || uid("model");
		this.device = device;
		Object.assign(this.userData, props.userData);
		this.material = props.material || null;
		const moduleMap = Object.fromEntries(this.props.modules?.map((module) => [module.name, module]) || []);
		const shaderInputs = props.shaderInputs || new ShaderInputs(moduleMap, { disableWarnings: this.props.disableWarnings });
		this.setShaderInputs(shaderInputs);
		const platformInfo = getPlatformInfo(device);
		const modules = (this.props.modules?.length > 0 ? this.props.modules : this.shaderInputs?.getModules()) || [];
		this.props.shaderLayout = mergeShaderModuleBindingsIntoLayout(this.props.shaderLayout, modules) || null;
		if (this.device.type === "webgpu" && this.props.source) {
			const { source, getUniforms, bindingTable } = this.props.shaderAssembler.assembleWGSLShader({
				platformInfo,
				...this.props,
				modules
			});
			this.source = source;
			this._getModuleUniforms = getUniforms;
			this._bindingTable = bindingTable;
			const inferredShaderLayout = device.getShaderLayout?.(this.source);
			this.props.shaderLayout = mergeShaderModuleBindingsIntoLayout(this.props.shaderLayout || inferredShaderLayout || null, modules) || null;
		} else {
			const { vs, fs, getUniforms } = this.props.shaderAssembler.assembleGLSLShaderPair({
				platformInfo,
				...this.props,
				modules
			});
			this.vs = vs;
			this.fs = fs;
			this._getModuleUniforms = getUniforms;
			this._bindingTable = [];
		}
		this.vertexCount = this.props.vertexCount;
		this.instanceCount = this.props.instanceCount;
		this.topology = this.props.topology;
		this.bufferLayout = this.props.bufferLayout;
		this.parameters = this.props.parameters;
		if (props.geometry) this.setGeometry(props.geometry);
		this.pipelineFactory = props.pipelineFactory || PipelineFactory.getDefaultPipelineFactory(this.device);
		this.shaderFactory = props.shaderFactory || ShaderFactory.getDefaultShaderFactory(this.device);
		this.pipeline = this._updatePipeline();
		this.vertexArray = device.createVertexArray({
			shaderLayout: this.pipeline.shaderLayout,
			bufferLayout: this.pipeline.bufferLayout
		});
		if (this._gpuGeometry) this._setGeometryAttributes(this._gpuGeometry);
		if ("isInstanced" in props) this.isInstanced = props.isInstanced;
		if (props.instanceCount) this.setInstanceCount(props.instanceCount);
		if (props.vertexCount) this.setVertexCount(props.vertexCount);
		if (props.indexBuffer) this.setIndexBuffer(props.indexBuffer);
		if (props.attributes) this.setAttributes(props.attributes);
		if (props.constantAttributes) this.setConstantAttributes(props.constantAttributes);
		if (props.bindings) this.setBindings(props.bindings);
		if (props.transformFeedback) this.transformFeedback = props.transformFeedback;
	}
	destroy() {
		if (!this._destroyed) {
			this.pipelineFactory.release(this.pipeline);
			this.shaderFactory.release(this.pipeline.vs);
			if (this.pipeline.fs && this.pipeline.fs !== this.pipeline.vs) this.shaderFactory.release(this.pipeline.fs);
			this._uniformStore.destroy();
			this._gpuGeometry?.destroy();
			this._destroyed = true;
		}
	}
	/** Query redraw status. Clears the status. */
	needsRedraw() {
		if (this._getBindingsUpdateTimestamp() > this._lastDrawTimestamp) this.setNeedsRedraw("contents of bound textures or buffers updated");
		const needsRedraw = this._needsRedraw;
		this._needsRedraw = false;
		return needsRedraw;
	}
	/** Mark the model as needing a redraw */
	setNeedsRedraw(reason) {
		this._needsRedraw ||= reason;
	}
	/** Returns WGSL binding debug rows for the assembled shader. Returns an empty array for GLSL models. */
	getBindingDebugTable() {
		return this._bindingTable;
	}
	/** Update uniforms and pipeline state prior to drawing. */
	predraw() {
		this.updateShaderInputs();
		this.pipeline = this._updatePipeline();
	}
	/**
	* Issue one draw call.
	* @param renderPass - render pass to draw into
	* @returns `true` if the draw call was executed, `false` if resources were not ready.
	*/
	draw(renderPass) {
		const loadingBinding = this._areBindingsLoading();
		if (loadingBinding) {
			log.info(LOG_DRAW_PRIORITY, `>>> DRAWING ABORTED ${this.id}: ${loadingBinding} not loaded`)();
			return false;
		}
		try {
			renderPass.pushDebugGroup(`${this}.predraw(${renderPass})`);
			this.predraw();
		} finally {
			renderPass.popDebugGroup();
		}
		let drawSuccess;
		let pipelineErrored = this.pipeline.isErrored;
		try {
			renderPass.pushDebugGroup(`${this}.draw(${renderPass})`);
			this._logDrawCallStart();
			this.pipeline = this._updatePipeline();
			pipelineErrored = this.pipeline.isErrored;
			if (pipelineErrored) {
				log.info(LOG_DRAW_PRIORITY, `>>> DRAWING ABORTED ${this.id}: ${PIPELINE_INITIALIZATION_FAILED}`)();
				drawSuccess = false;
			} else {
				const syncBindings = this._getBindings();
				const syncBindGroups = this._getBindGroups();
				const { indexBuffer } = this.vertexArray;
				const indexCount = indexBuffer ? indexBuffer.byteLength / (indexBuffer.indexType === "uint32" ? 4 : 2) : void 0;
				drawSuccess = this.pipeline.draw({
					renderPass,
					vertexArray: this.vertexArray,
					isInstanced: this.isInstanced,
					vertexCount: this.vertexCount,
					instanceCount: this.instanceCount,
					indexCount,
					transformFeedback: this.transformFeedback || void 0,
					bindings: syncBindings,
					bindGroups: syncBindGroups,
					_bindGroupCacheKeys: this._getBindGroupCacheKeys(),
					uniforms: this.props.uniforms,
					parameters: this.parameters,
					topology: this.topology
				});
			}
		} finally {
			renderPass.popDebugGroup();
			this._logDrawCallEnd();
		}
		this._logFramebuffer(renderPass);
		if (drawSuccess) {
			this._lastDrawTimestamp = this.device.timestamp;
			this._needsRedraw = false;
		} else if (pipelineErrored) this._needsRedraw = PIPELINE_INITIALIZATION_FAILED;
		else this._needsRedraw = "waiting for resource initialization";
		return drawSuccess;
	}
	/**
	* Updates the optional geometry
	* Geometry, set topology and bufferLayout
	* @note Can trigger a pipeline rebuild / pipeline cache fetch on WebGPU
	*/
	setGeometry(geometry) {
		this._gpuGeometry?.destroy();
		const gpuGeometry = geometry && makeGPUGeometry(this.device, geometry);
		if (gpuGeometry) {
			this.setTopology(gpuGeometry.topology || "triangle-list");
			const bufferLayoutHelper = new BufferLayoutHelper(this.bufferLayout);
			this.bufferLayout = bufferLayoutHelper.mergeBufferLayouts(gpuGeometry.bufferLayout, this.bufferLayout);
			if (this.vertexArray) this._setGeometryAttributes(gpuGeometry);
		}
		this._gpuGeometry = gpuGeometry;
	}
	/**
	* Updates the primitive topology ('triangle-list', 'triangle-strip' etc).
	* @note Triggers a pipeline rebuild / pipeline cache fetch on WebGPU
	*/
	setTopology(topology) {
		if (topology !== this.topology) {
			this.topology = topology;
			this._setPipelineNeedsUpdate("topology");
		}
	}
	/**
	* Updates the buffer layout.
	* @note Triggers a pipeline rebuild / pipeline cache fetch
	*/
	setBufferLayout(bufferLayout) {
		const bufferLayoutHelper = new BufferLayoutHelper(this.bufferLayout);
		this.bufferLayout = this._gpuGeometry ? bufferLayoutHelper.mergeBufferLayouts(bufferLayout, this._gpuGeometry.bufferLayout) : bufferLayout;
		this._setPipelineNeedsUpdate("bufferLayout");
		this.pipeline = this._updatePipeline();
		this.vertexArray = this.device.createVertexArray({
			shaderLayout: this.pipeline.shaderLayout,
			bufferLayout: this.pipeline.bufferLayout
		});
		if (this._gpuGeometry) this._setGeometryAttributes(this._gpuGeometry);
	}
	/**
	* Set GPU parameters.
	* @note Can trigger a pipeline rebuild / pipeline cache fetch.
	* @param parameters
	*/
	setParameters(parameters) {
		if (!deepEqual(parameters, this.parameters, 2)) {
			this.parameters = parameters;
			this._setPipelineNeedsUpdate("parameters");
		}
	}
	/**
	* Updates the instance count (used in draw calls)
	* @note Any attributes with stepMode=instance need to be at least this big
	*/
	setInstanceCount(instanceCount) {
		this.instanceCount = instanceCount;
		if (this.isInstanced === void 0 && instanceCount > 0) this.isInstanced = true;
		this.setNeedsRedraw("instanceCount");
	}
	/**
	* Updates the vertex count (used in draw calls)
	* @note Any attributes with stepMode=vertex need to be at least this big
	*/
	setVertexCount(vertexCount) {
		this.vertexCount = vertexCount;
		this.setNeedsRedraw("vertexCount");
	}
	/** Set the shader inputs */
	setShaderInputs(shaderInputs) {
		this.shaderInputs = shaderInputs;
		this._uniformStore = new UniformStore(this.device, this.shaderInputs.modules);
		for (const [moduleName, module] of Object.entries(this.shaderInputs.modules)) if (shaderModuleHasUniforms(module) && !this.material?.ownsModule(moduleName)) {
			const uniformBuffer = this._uniformStore.getManagedUniformBuffer(moduleName);
			this.bindings[`${moduleName}Uniforms`] = uniformBuffer;
		}
		this.setNeedsRedraw("shaderInputs");
	}
	setMaterial(material) {
		this.material = material;
		this.setNeedsRedraw("material");
	}
	/** Update uniform buffers from the model's shader inputs */
	updateShaderInputs() {
		this._uniformStore.setUniforms(this.shaderInputs.getUniformValues());
		this.setBindings(this._getNonMaterialBindings(this.shaderInputs.getBindingValues()));
		this.setNeedsRedraw("shaderInputs");
	}
	/**
	* Sets bindings (textures, samplers, uniform buffers)
	*/
	setBindings(bindings) {
		Object.assign(this.bindings, bindings);
		this.setNeedsRedraw("bindings");
	}
	/**
	* Updates optional transform feedback. WebGL only.
	*/
	setTransformFeedback(transformFeedback) {
		this.transformFeedback = transformFeedback;
		this.setNeedsRedraw("transformFeedback");
	}
	/**
	* Sets the index buffer
	* @todo - how to unset it if we change geometry?
	*/
	setIndexBuffer(indexBuffer) {
		this.vertexArray.setIndexBuffer(indexBuffer);
		this.setNeedsRedraw("indexBuffer");
	}
	/**
	* Sets attributes (buffers)
	* @note Overrides any attributes previously set with the same name
	*/
	setAttributes(buffers, options) {
		const disableWarnings = options?.disableWarnings ?? this.props.disableWarnings;
		if (buffers["indices"]) log.warn(`Model:${this.id} setAttributes() - indexBuffer should be set using setIndexBuffer()`)();
		this.bufferLayout = sortedBufferLayoutByShaderSourceLocations(this.pipeline.shaderLayout, this.bufferLayout);
		const bufferLayoutHelper = new BufferLayoutHelper(this.bufferLayout);
		for (const [bufferName, buffer] of Object.entries(buffers)) {
			const bufferLayout = bufferLayoutHelper.getBufferLayout(bufferName);
			if (!bufferLayout) {
				if (!disableWarnings) log.warn(`Model(${this.id}): Missing layout for buffer "${bufferName}".`)();
				continue;
			}
			const attributeNames = bufferLayoutHelper.getAttributeNamesForBuffer(bufferLayout);
			let set = false;
			for (const attributeName of attributeNames) {
				const attributeInfo = this._attributeInfos[attributeName];
				if (attributeInfo) {
					const location = this.device.type === "webgpu" ? bufferLayoutHelper.getBufferIndex(attributeInfo.bufferName) : attributeInfo.location;
					this.vertexArray.setBuffer(location, buffer);
					set = true;
				}
			}
			if (!set && !disableWarnings) log.warn(`Model(${this.id}): Ignoring buffer "${buffer.id}" for unknown attribute "${bufferName}"`)();
		}
		this.setNeedsRedraw("attributes");
	}
	/**
	* Sets constant attributes
	* @note Overrides any attributes previously set with the same name
	* Constant attributes are only supported in WebGL, not in WebGPU
	* Any attribute that is disabled in the current vertex array object
	* is read from the context's global constant value for that attribute location.
	* @param constantAttributes
	*/
	setConstantAttributes(attributes, options) {
		for (const [attributeName, value] of Object.entries(attributes)) {
			const attributeInfo = this._attributeInfos[attributeName];
			if (attributeInfo) this.vertexArray.setConstantWebGL(attributeInfo.location, value);
			else if (!(options?.disableWarnings ?? this.props.disableWarnings)) log.warn(`Model "${this.id}: Ignoring constant supplied for unknown attribute "${attributeName}"`)();
		}
		this.setNeedsRedraw("constants");
	}
	/** Check that bindings are loaded. Returns id of first binding that is still loading. */
	_areBindingsLoading() {
		for (const binding of Object.values(this.bindings)) if (binding instanceof DynamicTexture && !binding.isReady) return binding.id;
		for (const binding of Object.values(this.material?.bindings || {})) if (binding instanceof DynamicTexture && !binding.isReady) return binding.id;
		return false;
	}
	/** Extracts texture view from loaded async textures. Returns null if any textures have not yet been loaded. */
	_getBindings() {
		const validBindings = {};
		for (const [name, binding] of Object.entries(this.bindings)) if (binding instanceof DynamicTexture) {
			if (binding.isReady) validBindings[name] = binding.texture;
		} else validBindings[name] = binding;
		return validBindings;
	}
	_getBindGroups() {
		const shaderLayout = this.pipeline?.shaderLayout || this.props.shaderLayout || { bindings: [] };
		const bindGroups = shaderLayout.bindings.length ? normalizeBindingsByGroup(shaderLayout, this._getBindings()) : { 0: this._getBindings() };
		if (!this.material) return bindGroups;
		for (const [groupKey, groupBindings] of Object.entries(this.material.getBindingsByGroup())) {
			const group = Number(groupKey);
			bindGroups[group] = {
				...bindGroups[group] || {},
				...groupBindings
			};
		}
		return bindGroups;
	}
	_getBindGroupCacheKeys() {
		const bindGroupCacheKey = this.material?.getBindGroupCacheKey(3);
		return bindGroupCacheKey ? { 3: bindGroupCacheKey } : {};
	}
	/** Get the timestamp of the latest updated bound GPU memory resource (buffer/texture). */
	_getBindingsUpdateTimestamp() {
		let timestamp = 0;
		for (const binding of Object.values(this.bindings)) if (binding instanceof TextureView) timestamp = Math.max(timestamp, binding.texture.updateTimestamp);
		else if (binding instanceof Buffer || binding instanceof Texture) timestamp = Math.max(timestamp, binding.updateTimestamp);
		else if (binding instanceof DynamicTexture) timestamp = binding.texture ? Math.max(timestamp, binding.texture.updateTimestamp) : Infinity;
		else if (!(binding instanceof Sampler)) timestamp = Math.max(timestamp, binding.buffer.updateTimestamp);
		return Math.max(timestamp, this.material?.getBindingsUpdateTimestamp() || 0);
	}
	/**
	* Updates the optional geometry attributes
	* Geometry, sets several attributes, indexBuffer, and also vertex count
	* @note Can trigger a pipeline rebuild / pipeline cache fetch on WebGPU
	*/
	_setGeometryAttributes(gpuGeometry) {
		const attributes = { ...gpuGeometry.attributes };
		for (const [attributeName] of Object.entries(attributes)) if (!this.pipeline.shaderLayout.attributes.find((layout) => layout.name === attributeName) && attributeName !== "positions") delete attributes[attributeName];
		this.vertexCount = gpuGeometry.vertexCount;
		this.setIndexBuffer(gpuGeometry.indices || null);
		this.setAttributes(gpuGeometry.attributes, { disableWarnings: true });
		this.setAttributes(attributes, { disableWarnings: this.props.disableWarnings });
		this.setNeedsRedraw("geometry attributes");
	}
	/** Mark pipeline as needing update */
	_setPipelineNeedsUpdate(reason) {
		this._pipelineNeedsUpdate ||= reason;
		this.setNeedsRedraw(reason);
	}
	/** Update pipeline if needed */
	_updatePipeline() {
		if (this._pipelineNeedsUpdate) {
			let prevShaderVs = null;
			let prevShaderFs = null;
			if (this.pipeline) {
				log.log(1, `Model ${this.id}: Recreating pipeline because "${this._pipelineNeedsUpdate}".`)();
				prevShaderVs = this.pipeline.vs;
				prevShaderFs = this.pipeline.fs;
			}
			this._pipelineNeedsUpdate = false;
			const vs = this.shaderFactory.createShader({
				id: `${this.id}-vertex`,
				stage: "vertex",
				source: this.source || this.vs,
				debugShaders: this.props.debugShaders
			});
			let fs = null;
			if (this.source) fs = vs;
			else if (this.fs) fs = this.shaderFactory.createShader({
				id: `${this.id}-fragment`,
				stage: "fragment",
				source: this.source || this.fs,
				debugShaders: this.props.debugShaders
			});
			this.pipeline = this.pipelineFactory.createRenderPipeline({
				...this.props,
				bindings: void 0,
				bufferLayout: this.bufferLayout,
				topology: this.topology,
				parameters: this.parameters,
				bindGroups: this._getBindGroups(),
				vs,
				fs
			});
			this._attributeInfos = getAttributeInfosFromLayouts(this.pipeline.shaderLayout, this.bufferLayout);
			if (prevShaderVs) this.shaderFactory.release(prevShaderVs);
			if (prevShaderFs && prevShaderFs !== prevShaderVs) this.shaderFactory.release(prevShaderFs);
		}
		return this.pipeline;
	}
	/** Throttle draw call logging */
	_lastLogTime = 0;
	_logOpen = false;
	_logDrawCallStart() {
		const logDrawTimeout = log.level > 3 ? 0 : LOG_DRAW_TIMEOUT;
		if (log.level < 2 || Date.now() - this._lastLogTime < logDrawTimeout) return;
		this._lastLogTime = Date.now();
		this._logOpen = true;
		log.group(LOG_DRAW_PRIORITY, `>>> DRAWING MODEL ${this.id}`, { collapsed: log.level <= 2 })();
	}
	_logDrawCallEnd() {
		if (this._logOpen) {
			const shaderLayoutTable = getDebugTableForShaderLayout(this.pipeline.shaderLayout, this.id);
			log.table(LOG_DRAW_PRIORITY, shaderLayoutTable)();
			const uniformTable = this.shaderInputs.getDebugTable();
			log.table(LOG_DRAW_PRIORITY, uniformTable)();
			const attributeTable = this._getAttributeDebugTable();
			log.table(LOG_DRAW_PRIORITY, this._attributeInfos)();
			log.table(LOG_DRAW_PRIORITY, attributeTable)();
			log.groupEnd(LOG_DRAW_PRIORITY)();
			this._logOpen = false;
		}
	}
	_drawCount = 0;
	_logFramebuffer(renderPass) {
		const debugFramebuffers = this.device.props.debugFramebuffers;
		this._drawCount++;
		if (!debugFramebuffers) return;
		const framebuffer = renderPass.props.framebuffer;
		debugFramebuffer(renderPass, framebuffer, {
			id: framebuffer?.id || `${this.id}-framebuffer`,
			minimap: true
		});
	}
	_getAttributeDebugTable() {
		const table = {};
		for (const [name, attributeInfo] of Object.entries(this._attributeInfos)) {
			const values = this.vertexArray.attributes[attributeInfo.location];
			table[attributeInfo.location] = {
				name,
				type: attributeInfo.shaderType,
				values: values ? this._getBufferOrConstantValues(values, attributeInfo.bufferDataType) : "null"
			};
		}
		if (this.vertexArray.indexBuffer) {
			const { indexBuffer } = this.vertexArray;
			const values = indexBuffer.indexType === "uint32" ? new Uint32Array(indexBuffer.debugData) : new Uint16Array(indexBuffer.debugData);
			table["indices"] = {
				name: "indices",
				type: indexBuffer.indexType,
				values: values.toString()
			};
		}
		return table;
	}
	_getBufferOrConstantValues(attribute, dataType) {
		const TypedArrayConstructor = dataTypeDecoder.getTypedArrayConstructor(dataType);
		return (attribute instanceof Buffer ? new TypedArrayConstructor(attribute.debugData) : attribute).toString();
	}
	_getNonMaterialBindings(bindings) {
		if (!this.material) return bindings;
		const filteredBindings = {};
		for (const [name, binding] of Object.entries(bindings)) if (!this.material.ownsBinding(name)) filteredBindings[name] = binding;
		return filteredBindings;
	}
};
/** Create a shadertools platform info from the Device */
function getPlatformInfo(device) {
	return {
		type: device.type,
		shaderLanguage: device.info.shadingLanguage,
		shaderLanguageVersion: device.info.shadingLanguageVersion,
		gpu: device.info.gpu,
		features: device.features
	};
}
//#endregion
//#region node_modules/@luma.gl/engine/dist/compute/buffer-transform.js
/**
* Manages a WebGL program (pipeline) for buffer→buffer transforms.
* @note Only works under WebGL2.
*/
var BufferTransform = class BufferTransform {
	device;
	model;
	transformFeedback;
	static defaultProps = {
		...Model.defaultProps,
		outputs: void 0,
		feedbackBuffers: void 0
	};
	static isSupported(device) {
		return device?.info?.type === "webgl";
	}
	constructor(device, props = BufferTransform.defaultProps) {
		if (!BufferTransform.isSupported(device)) throw new Error("BufferTransform not yet implemented on WebGPU");
		this.device = device;
		this.model = new Model(this.device, {
			id: props.id || "buffer-transform-model",
			fs: props.fs || getPassthroughFS(),
			topology: props.topology || "point-list",
			varyings: props.outputs || props.varyings,
			...props
		});
		this.transformFeedback = this.device.createTransformFeedback({
			layout: this.model.pipeline.shaderLayout,
			buffers: props.feedbackBuffers
		});
		this.model.setTransformFeedback(this.transformFeedback);
		Object.seal(this);
	}
	/** Destroy owned resources. */
	destroy() {
		if (this.model) this.model.destroy();
	}
	/** @deprecated Use {@link destroy}. */
	delete() {
		this.destroy();
	}
	/** Run one transform loop. */
	run(options) {
		if (options?.inputBuffers) this.model.setAttributes(options.inputBuffers);
		if (options?.outputBuffers) this.transformFeedback.setBuffers(options.outputBuffers);
		const renderPass = this.device.beginRenderPass(options);
		this.model.draw(renderPass);
		renderPass.end();
	}
	/** @deprecated App knows what buffers it is passing in - Returns the {@link Buffer} or {@link BufferRange} for given varying name. */
	getBuffer(varyingName) {
		return this.transformFeedback.getBuffer(varyingName);
	}
	/** @deprecated App knows what buffers it is passing in - Reads the {@link Buffer} or {@link BufferRange} for given varying name. */
	readAsync(varyingName) {
		const result = this.getBuffer(varyingName);
		if (!result) throw new Error("BufferTransform#getBuffer");
		if (result instanceof Buffer) return result.readAsync();
		const { buffer, byteOffset = 0, byteLength = buffer.byteLength } = result;
		return buffer.readAsync(byteOffset, byteLength);
	}
};
//#endregion
//#region node_modules/@luma.gl/engine/dist/geometry/geometry.js
var Geometry = class {
	id;
	/** Determines how vertices are read from the 'vertex' attributes */
	topology;
	vertexCount;
	indices;
	attributes;
	userData = {};
	constructor(props) {
		const { attributes = {}, indices = null, vertexCount = null } = props;
		this.id = props.id || uid("geometry");
		this.topology = props.topology;
		if (indices) this.indices = ArrayBuffer.isView(indices) ? {
			value: indices,
			size: 1
		} : indices;
		this.attributes = {};
		for (const [attributeName, attributeValue] of Object.entries(attributes)) {
			const attribute = ArrayBuffer.isView(attributeValue) ? { value: attributeValue } : attributeValue;
			if (!ArrayBuffer.isView(attribute.value)) throw new Error(`${this._print(attributeName)}: must be typed array or object with value as typed array`);
			if ((attributeName === "POSITION" || attributeName === "positions") && !attribute.size) attribute.size = 3;
			if (attributeName === "indices") {
				if (this.indices) throw new Error("Multiple indices detected");
				this.indices = attribute;
			} else this.attributes[attributeName] = attribute;
		}
		if (this.indices && this.indices["isIndexed"] !== void 0) {
			this.indices = Object.assign({}, this.indices);
			delete this.indices["isIndexed"];
		}
		this.vertexCount = vertexCount || this._calculateVertexCount(this.attributes, this.indices);
	}
	getVertexCount() {
		return this.vertexCount;
	}
	/**
	* Return an object with all attributes plus indices added as a field.
	* TODO Geometry types are a mess
	*/
	getAttributes() {
		return this.indices ? {
			indices: this.indices,
			...this.attributes
		} : this.attributes;
	}
	_print(attributeName) {
		return `Geometry ${this.id} attribute ${attributeName}`;
	}
	/**
	* GeometryAttribute
	* value: typed array
	* type: indices, vertices, uvs
	* size: elements per vertex
	* target: WebGL buffer type (string or constant)
	*
	* @param attributes
	* @param indices
	* @returns
	*/
	_setAttributes(attributes, indices) {
		return this;
	}
	_calculateVertexCount(attributes, indices) {
		if (indices) return indices.value.length;
		let vertexCount = Infinity;
		for (const attribute of Object.values(attributes)) {
			const { value, size, constant } = attribute;
			if (!constant && value && size !== void 0 && size >= 1) vertexCount = Math.min(vertexCount, value.length / size);
		}
		return vertexCount;
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/attribute/gl-utils.js
function typedArrayFromDataType(type) {
	switch (type) {
		case "float64": return Float64Array;
		case "uint8":
		case "unorm8": return Uint8ClampedArray;
		default: return getTypedArrayConstructor(type);
	}
}
var dataTypeFromTypedArray = dataTypeDecoder.getDataType.bind(dataTypeDecoder);
function getBufferAttributeLayout(name, accessor, deviceType) {
	if (accessor.size > 4) return null;
	const type = deviceType === "webgpu" && accessor.type === "uint8" ? "unorm8" : accessor.type;
	return {
		attribute: name,
		format: accessor.size > 1 ? `${type}x${accessor.size}` : accessor.type,
		byteOffset: accessor.offset || 0
	};
}
function getStride(accessor) {
	return accessor.stride || accessor.size * accessor.bytesPerElement;
}
function bufferLayoutEqual(accessor1, accessor2) {
	return accessor1.type === accessor2.type && accessor1.size === accessor2.size && getStride(accessor1) === getStride(accessor2) && (accessor1.offset || 0) === (accessor2.offset || 0);
}
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/attribute/data-column.js
function resolveShaderAttribute(baseAccessor, shaderAttributeOptions) {
	if (shaderAttributeOptions.offset) defaultLogger.removed("shaderAttribute.offset", "vertexOffset, elementOffset")();
	const stride = getStride(baseAccessor);
	const vertexOffset = shaderAttributeOptions.vertexOffset !== void 0 ? shaderAttributeOptions.vertexOffset : baseAccessor.vertexOffset || 0;
	const elementOffset = shaderAttributeOptions.elementOffset || 0;
	const offset = vertexOffset * stride + elementOffset * baseAccessor.bytesPerElement + (baseAccessor.offset || 0);
	return {
		...shaderAttributeOptions,
		offset,
		stride
	};
}
function resolveDoublePrecisionShaderAttributes(baseAccessor, shaderAttributeOptions) {
	const resolvedOptions = resolveShaderAttribute(baseAccessor, shaderAttributeOptions);
	return {
		high: resolvedOptions,
		low: {
			...resolvedOptions,
			offset: resolvedOptions.offset + baseAccessor.size * 4
		}
	};
}
var DataColumn = class {
	constructor(device, opts, state) {
		this._buffer = null;
		this.device = device;
		this.id = opts.id || "";
		this.size = opts.size || 1;
		const logicalType = opts.logicalType || opts.type;
		const doublePrecision = logicalType === "float64";
		let { defaultValue } = opts;
		defaultValue = Number.isFinite(defaultValue) ? [defaultValue] : defaultValue || new Array(this.size).fill(0);
		let bufferType;
		if (doublePrecision) bufferType = "float32";
		else if (!logicalType && opts.isIndexed) bufferType = "uint32";
		else bufferType = logicalType || "float32";
		let defaultType = typedArrayFromDataType(logicalType || bufferType);
		this.doublePrecision = doublePrecision;
		if (doublePrecision && opts.fp64 === false) defaultType = Float32Array;
		this.value = null;
		this.settings = {
			...opts,
			defaultType,
			defaultValue,
			logicalType,
			type: bufferType,
			normalized: bufferType.includes("norm"),
			size: this.size,
			bytesPerElement: defaultType.BYTES_PER_ELEMENT
		};
		this.state = {
			...state,
			externalBuffer: null,
			bufferAccessor: this.settings,
			allocatedValue: null,
			numInstances: 0,
			bounds: null,
			constant: false
		};
	}
	get isConstant() {
		return this.state.constant;
	}
	get buffer() {
		return this._buffer;
	}
	get byteOffset() {
		const accessor = this.getAccessor();
		if (accessor.vertexOffset) return accessor.vertexOffset * getStride(accessor);
		return 0;
	}
	get numInstances() {
		return this.state.numInstances;
	}
	set numInstances(n) {
		this.state.numInstances = n;
	}
	delete() {
		if (this._buffer) {
			this._buffer.delete();
			this._buffer = null;
		}
		typed_array_manager_default.release(this.state.allocatedValue);
	}
	getBuffer() {
		if (this.state.constant) return null;
		return this.state.externalBuffer || this._buffer;
	}
	getValue(attributeName = this.id, options = null) {
		const result = {};
		if (this.state.constant) {
			const value = this.value;
			if (options) {
				const shaderAttributeDef = resolveShaderAttribute(this.getAccessor(), options);
				const offset = shaderAttributeDef.offset / value.BYTES_PER_ELEMENT;
				const size = shaderAttributeDef.size || this.size;
				result[attributeName] = value.subarray(offset, offset + size);
			} else result[attributeName] = value;
		} else result[attributeName] = this.getBuffer();
		if (this.doublePrecision) if (this.value instanceof Float64Array) result[`${attributeName}64Low`] = result[attributeName];
		else result[`${attributeName}64Low`] = new Float32Array(this.size);
		return result;
	}
	_getBufferLayout(attributeName = this.id, options = null) {
		const accessor = this.getAccessor();
		const attributes = [];
		const result = {
			name: this.id,
			byteStride: getStride(accessor)
		};
		if (this.doublePrecision) {
			const doubleShaderAttributeDefs = resolveDoublePrecisionShaderAttributes(accessor, options || {});
			attributes.push(getBufferAttributeLayout(attributeName, {
				...accessor,
				...doubleShaderAttributeDefs.high
			}, this.device.type), getBufferAttributeLayout(`${attributeName}64Low`, {
				...accessor,
				...doubleShaderAttributeDefs.low
			}, this.device.type));
		} else if (options) {
			const shaderAttributeDef = resolveShaderAttribute(accessor, options);
			attributes.push(getBufferAttributeLayout(attributeName, {
				...accessor,
				...shaderAttributeDef
			}, this.device.type));
		} else attributes.push(getBufferAttributeLayout(attributeName, accessor, this.device.type));
		result.attributes = attributes.filter(Boolean);
		return result;
	}
	setAccessor(accessor) {
		this.state.bufferAccessor = accessor;
	}
	getAccessor() {
		return this.state.bufferAccessor;
	}
	getBounds() {
		if (this.state.bounds) return this.state.bounds;
		let result = null;
		if (this.state.constant && this.value) {
			const min = Array.from(this.value);
			result = [min, min];
		} else {
			const { value, numInstances, size } = this;
			const len = numInstances * size;
			if (value && len && value.length >= len) {
				const min = new Array(size).fill(Infinity);
				const max = new Array(size).fill(-Infinity);
				for (let i = 0; i < len;) for (let j = 0; j < size; j++) {
					const v = value[i++];
					if (v < min[j]) min[j] = v;
					if (v > max[j]) max[j] = v;
				}
				result = [min, max];
			}
		}
		this.state.bounds = result;
		return result;
	}
	setData(data) {
		const { state } = this;
		let opts;
		if (ArrayBuffer.isView(data)) opts = { value: data };
		else if (data instanceof Buffer) opts = { buffer: data };
		else opts = data;
		const accessor = {
			...this.settings,
			...opts
		};
		if (ArrayBuffer.isView(opts.value)) {
			if (!opts.type) if (this.doublePrecision && opts.value instanceof Float64Array) accessor.type = "float32";
			else {
				const type = dataTypeFromTypedArray(opts.value);
				accessor.type = accessor.normalized ? type.replace("int", "norm") : type;
			}
			accessor.bytesPerElement = opts.value.BYTES_PER_ELEMENT;
			accessor.stride = getStride(accessor);
		}
		state.bounds = null;
		if (opts.constant) {
			let value = opts.value;
			value = this._normalizeValue(value, [], 0);
			if (this.settings.normalized) value = this.normalizeConstant(value);
			if (!(!state.constant || !this._areValuesEqual(value, this.value))) return false;
			state.externalBuffer = null;
			state.constant = true;
			this.value = ArrayBuffer.isView(value) ? value : new Float32Array(value);
		} else if (opts.buffer) {
			state.externalBuffer = opts.buffer;
			state.constant = false;
			this.value = opts.value || null;
		} else if (opts.value) {
			this._checkExternalBuffer(opts);
			let value = opts.value;
			state.externalBuffer = null;
			state.constant = false;
			this.value = value;
			let { buffer } = this;
			const stride = getStride(accessor);
			const byteOffset = (accessor.vertexOffset || 0) * stride;
			if (this.doublePrecision && value instanceof Float64Array) value = toDoublePrecisionArray(value, accessor);
			if (this.settings.isIndexed) {
				const ArrayType = this.settings.defaultType;
				if (value.constructor !== ArrayType) value = new ArrayType(value);
			}
			const requiredBufferSize = value.byteLength + byteOffset + stride * 2;
			if (!buffer || buffer.byteLength < requiredBufferSize) buffer = this._createBuffer(requiredBufferSize);
			buffer.write(value, byteOffset);
		}
		this.setAccessor(accessor);
		return true;
	}
	updateSubBuffer(opts = {}) {
		this.state.bounds = null;
		const value = this.value;
		const { startOffset = 0, endOffset } = opts;
		this.buffer.write(this.doublePrecision && value instanceof Float64Array ? toDoublePrecisionArray(value, {
			size: this.size,
			startIndex: startOffset,
			endIndex: endOffset
		}) : value.subarray(startOffset, endOffset), startOffset * value.BYTES_PER_ELEMENT + this.byteOffset);
	}
	allocate(numInstances, copy = false) {
		const { state } = this;
		const oldValue = state.allocatedValue;
		const value = typed_array_manager_default.allocate(oldValue, numInstances + 1, {
			size: this.size,
			type: this.settings.defaultType,
			copy
		});
		this.value = value;
		const { byteOffset } = this;
		let { buffer } = this;
		if (!buffer || buffer.byteLength < value.byteLength + byteOffset) {
			buffer = this._createBuffer(value.byteLength + byteOffset);
			if (copy && oldValue) buffer.write(oldValue instanceof Float64Array ? toDoublePrecisionArray(oldValue, this) : oldValue, byteOffset);
		}
		state.allocatedValue = value;
		state.constant = false;
		state.externalBuffer = null;
		this.setAccessor(this.settings);
		return true;
	}
	_checkExternalBuffer(opts) {
		const { value } = opts;
		if (!ArrayBuffer.isView(value)) throw new Error(`Attribute ${this.id} value is not TypedArray`);
		const ArrayType = this.settings.defaultType;
		let illegalArrayType = false;
		if (this.doublePrecision) illegalArrayType = value.BYTES_PER_ELEMENT < 4;
		if (illegalArrayType) throw new Error(`Attribute ${this.id} does not support ${value.constructor.name}`);
		if (!(value instanceof ArrayType) && this.settings.normalized && !("normalized" in opts)) defaultLogger.warn(`Attribute ${this.id} is normalized`)();
	}
	normalizeConstant(value) {
		switch (this.settings.type) {
			case "snorm8": return new Float32Array(value).map((x) => (x + 128) / 255 * 2 - 1);
			case "snorm16": return new Float32Array(value).map((x) => (x + 32768) / 65535 * 2 - 1);
			case "unorm8": return new Float32Array(value).map((x) => x / 255);
			case "unorm16": return new Float32Array(value).map((x) => x / 65535);
			default: return value;
		}
	}
	_normalizeValue(value, out, start) {
		const { defaultValue, size } = this.settings;
		if (Number.isFinite(value)) {
			out[start] = value;
			return out;
		}
		if (!value) {
			let i = size;
			while (--i >= 0) out[start + i] = defaultValue[i];
			return out;
		}
		switch (size) {
			case 4: out[start + 3] = Number.isFinite(value[3]) ? value[3] : defaultValue[3];
			case 3: out[start + 2] = Number.isFinite(value[2]) ? value[2] : defaultValue[2];
			case 2: out[start + 1] = Number.isFinite(value[1]) ? value[1] : defaultValue[1];
			case 1:
				out[start + 0] = Number.isFinite(value[0]) ? value[0] : defaultValue[0];
				break;
			default:
				let i = size;
				while (--i >= 0) out[start + i] = Number.isFinite(value[i]) ? value[i] : defaultValue[i];
		}
		return out;
	}
	_areValuesEqual(value1, value2) {
		if (!value1 || !value2) return false;
		const { size } = this;
		for (let i = 0; i < size; i++) if (value1[i] !== value2[i]) return false;
		return true;
	}
	_createBuffer(byteLength) {
		if (this._buffer) this._buffer.destroy();
		const { isIndexed, type } = this.settings;
		this._buffer = this.device.createBuffer({
			...this._buffer?.props,
			id: this.id,
			usage: (isIndexed ? Buffer.INDEX : Buffer.VERTEX) | Buffer.COPY_DST,
			indexType: isIndexed ? type : void 0,
			byteLength
		});
		return this._buffer;
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/utils/iterable-utils.js
var EMPTY_ARRAY$1 = [];
var placeholderArray = [];
function createIterable(data, startRow = 0, endRow = Infinity) {
	let iterable = EMPTY_ARRAY$1;
	const objectInfo = {
		index: -1,
		data,
		target: []
	};
	if (!data) iterable = EMPTY_ARRAY$1;
	else if (typeof data[Symbol.iterator] === "function") iterable = data;
	else if (data.length > 0) {
		placeholderArray.length = data.length;
		iterable = placeholderArray;
	}
	if (startRow > 0 || Number.isFinite(endRow)) {
		iterable = (Array.isArray(iterable) ? iterable : Array.from(iterable)).slice(startRow, endRow);
		objectInfo.index = startRow - 1;
	}
	return {
		iterable,
		objectInfo
	};
}
function isAsyncIterable(data) {
	return data && data[Symbol.asyncIterator];
}
function getAccessorFromBuffer(typedArray, options) {
	const { size, stride, offset, startIndices, nested } = options;
	const bytesPerElement = typedArray.BYTES_PER_ELEMENT;
	const elementStride = stride ? stride / bytesPerElement : size;
	const elementOffset = offset ? offset / bytesPerElement : 0;
	const vertexCount = Math.floor((typedArray.length - elementOffset) / elementStride);
	return (_, { index, target }) => {
		if (!startIndices) {
			const sourceIndex = index * elementStride + elementOffset;
			for (let j = 0; j < size; j++) target[j] = typedArray[sourceIndex + j];
			return target;
		}
		const startIndex = startIndices[index];
		const endIndex = startIndices[index + 1] || vertexCount;
		let result;
		if (nested) {
			result = new Array(endIndex - startIndex);
			for (let i = startIndex; i < endIndex; i++) {
				const sourceIndex = i * elementStride + elementOffset;
				target = new Array(size);
				for (let j = 0; j < size; j++) target[j] = typedArray[sourceIndex + j];
				result[i - startIndex] = target;
			}
		} else if (elementStride === size) result = typedArray.subarray(startIndex * size + elementOffset, endIndex * size + elementOffset);
		else {
			result = new typedArray.constructor((endIndex - startIndex) * size);
			let targetIndex = 0;
			for (let i = startIndex; i < endIndex; i++) {
				const sourceIndex = i * elementStride + elementOffset;
				for (let j = 0; j < size; j++) result[targetIndex++] = typedArray[sourceIndex + j];
			}
		}
		return result;
	};
}
//#endregion
//#region node_modules/@deck.gl/core/dist/utils/range.js
var EMPTY = [];
var FULL = [[0, Infinity]];
function add(rangeList, range) {
	if (rangeList === FULL) return rangeList;
	if (range[0] < 0) range[0] = 0;
	if (range[0] >= range[1]) return rangeList;
	const newRangeList = [];
	const len = rangeList.length;
	let insertPosition = 0;
	for (let i = 0; i < len; i++) {
		const range0 = rangeList[i];
		if (range0[1] < range[0]) {
			newRangeList.push(range0);
			insertPosition = i + 1;
		} else if (range0[0] > range[1]) newRangeList.push(range0);
		else range = [Math.min(range0[0], range[0]), Math.max(range0[1], range[1])];
	}
	newRangeList.splice(insertPosition, 0, range);
	return newRangeList;
}
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/attribute/transition-settings.js
var DEFAULT_TRANSITION_SETTINGS = {
	interpolation: {
		duration: 0,
		easing: (t) => t
	},
	spring: {
		stiffness: .05,
		damping: .5
	}
};
function normalizeTransitionSettings(userSettings, layerSettings) {
	if (!userSettings) return null;
	if (Number.isFinite(userSettings)) userSettings = {
		type: "interpolation",
		duration: userSettings
	};
	const type = userSettings.type || "interpolation";
	return {
		...DEFAULT_TRANSITION_SETTINGS[type],
		...layerSettings,
		...userSettings,
		type
	};
}
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/attribute/attribute.js
var Attribute = class extends DataColumn {
	constructor(device, opts) {
		super(device, opts, {
			startIndices: null,
			lastExternalBuffer: null,
			binaryValue: null,
			binaryAccessor: null,
			needsUpdate: true,
			needsRedraw: false,
			layoutChanged: false,
			updateRanges: FULL
		});
		/** Legacy approach to set attribute value - read `isConstant` instead for attribute state */
		this.constant = false;
		this.settings.update = opts.update || (opts.accessor ? this._autoUpdater : void 0);
		Object.seal(this.settings);
		Object.seal(this.state);
		this._validateAttributeUpdaters();
	}
	get startIndices() {
		return this.state.startIndices;
	}
	set startIndices(layout) {
		this.state.startIndices = layout;
	}
	needsUpdate() {
		return this.state.needsUpdate;
	}
	needsRedraw({ clearChangedFlags = false } = {}) {
		const needsRedraw = this.state.needsRedraw;
		this.state.needsRedraw = needsRedraw && !clearChangedFlags;
		return needsRedraw;
	}
	layoutChanged() {
		return this.state.layoutChanged;
	}
	setAccessor(accessor) {
		var _a;
		(_a = this.state).layoutChanged || (_a.layoutChanged = !bufferLayoutEqual(accessor, this.getAccessor()));
		super.setAccessor(accessor);
	}
	getUpdateTriggers() {
		const { accessor } = this.settings;
		return [this.id].concat(typeof accessor !== "function" && accessor || []);
	}
	supportsTransition() {
		return Boolean(this.settings.transition);
	}
	getTransitionSetting(opts) {
		if (!opts || !this.supportsTransition()) return null;
		const { accessor } = this.settings;
		const layerSettings = this.settings.transition;
		return normalizeTransitionSettings(Array.isArray(accessor) ? opts[accessor.find((a) => opts[a])] : opts[accessor], layerSettings);
	}
	setNeedsUpdate(reason = this.id, dataRange) {
		this.state.needsUpdate = this.state.needsUpdate || reason;
		this.setNeedsRedraw(reason);
		if (dataRange) {
			const { startRow = 0, endRow = Infinity } = dataRange;
			this.state.updateRanges = add(this.state.updateRanges, [startRow, endRow]);
		} else this.state.updateRanges = FULL;
	}
	clearNeedsUpdate() {
		this.state.needsUpdate = false;
		this.state.updateRanges = EMPTY;
	}
	setNeedsRedraw(reason = this.id) {
		this.state.needsRedraw = this.state.needsRedraw || reason;
	}
	allocate(numInstances) {
		const { state, settings } = this;
		if (settings.noAlloc) return false;
		if (settings.update) {
			super.allocate(numInstances, state.updateRanges !== FULL);
			return true;
		}
		return false;
	}
	updateBuffer({ numInstances, data, props, context }) {
		if (!this.needsUpdate()) return false;
		const { state: { updateRanges }, settings: { update, noAlloc } } = this;
		let updated = true;
		if (update) {
			for (const [startRow, endRow] of updateRanges) update.call(context, this, {
				data,
				startRow,
				endRow,
				props,
				numInstances
			});
			if (!this.value) {} else if (this.constant || !this.buffer || this.buffer.byteLength < this.value.byteLength + this.byteOffset) {
				if (this.constant) this.setConstantValue(context, this.value);
				else this.setData({
					value: this.value,
					constant: this.constant
				});
				this.constant = false;
			} else for (const [startRow, endRow] of updateRanges) {
				const startOffset = Number.isFinite(startRow) ? this.getVertexOffset(startRow) : 0;
				const endOffset = Number.isFinite(endRow) ? this.getVertexOffset(endRow) : noAlloc || !Number.isFinite(numInstances) ? this.value.length : numInstances * this.size;
				super.updateSubBuffer({
					startOffset,
					endOffset
				});
			}
			this._checkAttributeArray();
		} else updated = false;
		this.clearNeedsUpdate();
		this.setNeedsRedraw();
		return updated;
	}
	setConstantValue(context, value) {
		if (value === void 0 || typeof value === "function") return false;
		const transformedValue = this.settings.transform && context ? this.settings.transform.call(context, value) : value;
		if (this.device.type === "webgpu") return this.setConstantBufferValue(transformedValue, this.numInstances);
		if (this.setData({
			constant: true,
			value: transformedValue
		})) this.setNeedsRedraw();
		this.clearNeedsUpdate();
		return true;
	}
	setConstantBufferValue(value, numInstances) {
		const ArrayType = this.settings.defaultType;
		const constantValue = this._normalizeValue(value, new ArrayType(this.size), 0);
		if (this._hasConstantBufferValue(constantValue, numInstances)) {
			this.constant = false;
			this.clearNeedsUpdate();
			return false;
		}
		const repeatedValue = new ArrayType(Math.max(numInstances, 1) * this.size);
		for (let i = 0; i < repeatedValue.length; i += this.size) repeatedValue.set(constantValue, i);
		const hasChanged = this.setData({ value: repeatedValue });
		this.constant = false;
		this.clearNeedsUpdate();
		if (hasChanged) this.setNeedsRedraw();
		return hasChanged;
	}
	_hasConstantBufferValue(value, numInstances) {
		const currentValue = this.value;
		const expectedLength = Math.max(numInstances, 1) * this.size;
		if (!ArrayBuffer.isView(currentValue) || currentValue.length !== expectedLength || currentValue.length % this.size !== 0) return false;
		for (let i = 0; i < currentValue.length; i += this.size) for (let j = 0; j < this.size; j++) if (currentValue[i + j] !== value[j]) return false;
		return true;
	}
	setExternalBuffer(buffer) {
		const { state } = this;
		if (!buffer) {
			state.lastExternalBuffer = null;
			return false;
		}
		this.clearNeedsUpdate();
		if (state.lastExternalBuffer === buffer) return true;
		state.lastExternalBuffer = buffer;
		this.setNeedsRedraw();
		this.setData(buffer);
		return true;
	}
	setBinaryValue(buffer, startIndices = null) {
		const { state, settings } = this;
		if (!buffer) {
			state.binaryValue = null;
			state.binaryAccessor = null;
			return false;
		}
		if (settings.noAlloc) return false;
		if (state.binaryValue === buffer) {
			this.clearNeedsUpdate();
			return true;
		}
		state.binaryValue = buffer;
		this.setNeedsRedraw();
		if (settings.transform || startIndices !== this.startIndices) {
			if (ArrayBuffer.isView(buffer)) buffer = { value: buffer };
			const binaryValue = buffer;
			assert(ArrayBuffer.isView(binaryValue.value), `invalid ${settings.accessor}`);
			const needsNormalize = Boolean(binaryValue.size) && binaryValue.size !== this.size;
			state.binaryAccessor = getAccessorFromBuffer(binaryValue.value, {
				size: binaryValue.size || this.size,
				stride: binaryValue.stride,
				offset: binaryValue.offset,
				startIndices,
				nested: needsNormalize
			});
			return false;
		}
		this.clearNeedsUpdate();
		this.setData(buffer);
		return true;
	}
	getVertexOffset(row) {
		const { startIndices } = this;
		return (startIndices ? row < startIndices.length ? startIndices[row] : this.numInstances : row) * this.size;
	}
	getValue() {
		const shaderAttributeDefs = this.settings.shaderAttributes;
		const result = super.getValue();
		if (!shaderAttributeDefs) return result;
		for (const shaderAttributeName in shaderAttributeDefs) Object.assign(result, super.getValue(shaderAttributeName, shaderAttributeDefs[shaderAttributeName]));
		return result;
	}
	/** Generate WebGPU-style buffer layout descriptor from this attribute */
	getBufferLayout(modelInfo) {
		this.state.layoutChanged = false;
		const shaderAttributeDefs = this.settings.shaderAttributes;
		const result = super._getBufferLayout();
		const { stepMode } = this.settings;
		if (stepMode === "dynamic") result.stepMode = modelInfo ? modelInfo.isInstanced ? "instance" : "vertex" : "instance";
		else result.stepMode = stepMode ?? "vertex";
		if (!shaderAttributeDefs) return result;
		for (const shaderAttributeName in shaderAttributeDefs) {
			const map = super._getBufferLayout(shaderAttributeName, shaderAttributeDefs[shaderAttributeName]);
			result.attributes.push(...map.attributes);
		}
		return result;
	}
	_autoUpdater(attribute, { data, startRow, endRow, props, numInstances }) {
		const { settings, state, value, size, startIndices } = attribute;
		const { accessor, transform } = settings;
		const accessorFunc = state.binaryAccessor || (typeof accessor === "function" ? accessor : props[accessor]);
		assert(typeof accessorFunc === "function", `accessor "${accessor}" is not a function`);
		let i = attribute.getVertexOffset(startRow);
		const { iterable, objectInfo } = createIterable(data, startRow, endRow);
		for (const object of iterable) {
			objectInfo.index++;
			let objectValue = accessorFunc(object, objectInfo);
			if (transform) objectValue = transform.call(this, objectValue);
			if (startIndices) {
				const numVertices = (objectInfo.index < startIndices.length - 1 ? startIndices[objectInfo.index + 1] : numInstances) - startIndices[objectInfo.index];
				if (objectValue && Array.isArray(objectValue[0])) {
					let startIndex = i;
					for (const item of objectValue) {
						attribute._normalizeValue(item, value, startIndex);
						startIndex += size;
					}
				} else if (objectValue && objectValue.length > size) value.set(objectValue, i);
				else {
					attribute._normalizeValue(objectValue, objectInfo.target, 0);
					fillArray({
						target: value,
						source: objectInfo.target,
						start: i,
						count: numVertices
					});
				}
				i += numVertices * size;
			} else {
				attribute._normalizeValue(objectValue, value, i);
				i += size;
			}
		}
	}
	_validateAttributeUpdaters() {
		const { settings } = this;
		if (!(settings.noAlloc || typeof settings.update === "function")) throw new Error(`Attribute ${this.id} missing update or accessor`);
	}
	_checkAttributeArray() {
		const { value } = this;
		const limit = Math.min(4, this.size);
		if (value && value.length >= limit) {
			let valid = true;
			switch (limit) {
				case 4: valid = valid && Number.isFinite(value[3]);
				case 3: valid = valid && Number.isFinite(value[2]);
				case 2: valid = valid && Number.isFinite(value[1]);
				case 1:
					valid = valid && Number.isFinite(value[0]);
					break;
				default: valid = false;
			}
			if (!valid) throw new Error(`Illegal attribute generated for ${this.id}`);
		}
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/utils/array-utils.js
function padArrayChunk(options) {
	const { source, target, start = 0, size, getData } = options;
	const end = options.end || target.length;
	const sourceLength = source.length;
	const targetLength = end - start;
	if (sourceLength > targetLength) {
		target.set(source.subarray(0, targetLength), start);
		return;
	}
	target.set(source, start);
	if (!getData) return;
	let i = sourceLength;
	while (i < targetLength) {
		const datum = getData(i, source);
		for (let j = 0; j < size; j++) {
			target[start + i] = datum[j] || 0;
			i++;
		}
	}
}
function padArray({ source, target, size, getData, sourceStartIndices, targetStartIndices }) {
	if (!sourceStartIndices || !targetStartIndices) {
		padArrayChunk({
			source,
			target,
			size,
			getData
		});
		return target;
	}
	let sourceIndex = 0;
	let targetIndex = 0;
	const getChunkData = getData && ((i, chunk) => getData(i + targetIndex, chunk));
	const n = Math.min(sourceStartIndices.length, targetStartIndices.length);
	for (let i = 1; i < n; i++) {
		const nextSourceIndex = sourceStartIndices[i] * size;
		const nextTargetIndex = targetStartIndices[i] * size;
		padArrayChunk({
			source: source.subarray(sourceIndex, nextSourceIndex),
			target,
			start: targetIndex,
			end: nextTargetIndex,
			size,
			getData: getChunkData
		});
		sourceIndex = nextSourceIndex;
		targetIndex = nextTargetIndex;
	}
	if (targetIndex < target.length) padArrayChunk({
		source: [],
		target,
		start: targetIndex,
		size,
		getData: getChunkData
	});
	return target;
}
//#endregion
//#region node_modules/@deck.gl/core/dist/transitions/gpu-transition-utils.js
/** Create a new empty attribute with the same settings: type, shader layout etc. */
function cloneAttribute(attribute) {
	const { device, settings, value } = attribute;
	const newAttribute = new Attribute(device, settings);
	newAttribute.setData({
		value: value instanceof Float64Array ? new Float64Array(0) : new Float32Array(0),
		normalized: settings.normalized
	});
	return newAttribute;
}
/** Returns the GLSL attribute type for the given number of float32 components. */
function getAttributeTypeFromSize(size) {
	switch (size) {
		case 1: return "float";
		case 2: return "vec2";
		case 3: return "vec3";
		case 4: return "vec4";
		default: throw new Error(`No defined attribute type for size "${size}"`);
	}
}
/** Returns the {@link VertexFormat} for the given number of float32 components. */
function getFloat32VertexFormat(size) {
	switch (size) {
		case 1: return "float32";
		case 2: return "float32x2";
		case 3: return "float32x3";
		case 4: return "float32x4";
		default: throw new Error("invalid type size");
	}
}
function cycleBuffers(buffers) {
	buffers.push(buffers.shift());
}
function getAttributeBufferLength(attribute, numInstances) {
	const { doublePrecision, settings, value, size } = attribute;
	const multiplier = doublePrecision && value instanceof Float64Array ? 2 : 1;
	let maxVertexOffset = 0;
	const { shaderAttributes } = attribute.settings;
	if (shaderAttributes) for (const shaderAttribute of Object.values(shaderAttributes)) maxVertexOffset = Math.max(maxVertexOffset, shaderAttribute.vertexOffset ?? 0);
	return (settings.noAlloc ? value.length : (numInstances + maxVertexOffset) * size) * multiplier;
}
function matchBuffer({ device, source, target }) {
	if (!target || target.byteLength < source.byteLength) {
		target?.destroy();
		target = device.createBuffer({
			byteLength: source.byteLength,
			usage: source.usage
		});
	}
	return target;
}
function padBuffer({ device, buffer, attribute, fromLength, toLength, fromStartIndices, getData = (x) => x }) {
	const precisionMultiplier = attribute.doublePrecision && attribute.value instanceof Float64Array ? 2 : 1;
	const size = attribute.size * precisionMultiplier;
	const byteOffset = attribute.byteOffset;
	const targetByteOffset = attribute.settings.bytesPerElement < 4 ? byteOffset / attribute.settings.bytesPerElement * 4 : byteOffset;
	const toStartIndices = attribute.startIndices;
	const hasStartIndices = fromStartIndices && toStartIndices;
	const isConstant = attribute.isConstant;
	if (!hasStartIndices && buffer && fromLength >= toLength) return buffer;
	const ArrayType = attribute.value instanceof Float64Array ? Float32Array : attribute.value.constructor;
	const toData = isConstant ? attribute.value : new ArrayType(attribute.getBuffer().readSyncWebGL(byteOffset, toLength * ArrayType.BYTES_PER_ELEMENT).buffer);
	if (attribute.settings.normalized && !isConstant) {
		const getter = getData;
		getData = (value, chunk) => attribute.normalizeConstant(getter(value, chunk));
	}
	const getMissingData = isConstant ? (i, chunk) => getData(toData, chunk) : (i, chunk) => getData(toData.subarray(i + byteOffset, i + byteOffset + size), chunk);
	const source = buffer ? new Float32Array(buffer.readSyncWebGL(targetByteOffset, fromLength * 4).buffer) : new Float32Array(0);
	const target = new Float32Array(toLength);
	padArray({
		source,
		target,
		sourceStartIndices: fromStartIndices,
		targetStartIndices: toStartIndices,
		size,
		getData: getMissingData
	});
	if (!buffer || buffer.byteLength < target.byteLength + targetByteOffset) {
		buffer?.destroy();
		buffer = device.createBuffer({
			byteLength: target.byteLength + targetByteOffset,
			usage: 35050
		});
	}
	buffer.write(target, targetByteOffset);
	return buffer;
}
//#endregion
//#region node_modules/@deck.gl/core/dist/transitions/gpu-transition.js
var GPUTransitionBase = class {
	constructor({ device, attribute, timeline }) {
		this.buffers = [];
		/** The vertex count of the last buffer.
		* Buffer may be larger than the actual length we want to use
		* because we only reallocate buffers when they grow, not when they shrink,
		* due to performance costs */
		this.currentLength = 0;
		this.device = device;
		this.transition = new Transition(timeline);
		this.attribute = attribute;
		this.attributeInTransition = cloneAttribute(attribute);
		this.currentStartIndices = attribute.startIndices;
	}
	get inProgress() {
		return this.transition.inProgress;
	}
	start(transitionSettings, numInstances, duration = Infinity) {
		this.settings = transitionSettings;
		this.currentStartIndices = this.attribute.startIndices;
		this.currentLength = getAttributeBufferLength(this.attribute, numInstances);
		this.transition.start({
			...transitionSettings,
			duration
		});
	}
	update() {
		const updated = this.transition.update();
		if (updated) this.onUpdate();
		return updated;
	}
	setBuffer(buffer) {
		this.attributeInTransition.setData({
			buffer,
			normalized: this.attribute.settings.normalized,
			value: this.attributeInTransition.value
		});
	}
	cancel() {
		this.transition.cancel();
	}
	delete() {
		this.cancel();
		for (const buffer of this.buffers) buffer.destroy();
		this.buffers.length = 0;
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/transitions/gpu-interpolation-transition.js
var GPUInterpolationTransition = class extends GPUTransitionBase {
	constructor({ device, attribute, timeline }) {
		super({
			device,
			attribute,
			timeline
		});
		this.type = "interpolation";
		this.transform = getTransform$1(device, attribute);
	}
	start(transitionSettings, numInstances) {
		const prevLength = this.currentLength;
		const prevStartIndices = this.currentStartIndices;
		super.start(transitionSettings, numInstances, transitionSettings.duration);
		if (transitionSettings.duration <= 0) {
			this.transition.cancel();
			return;
		}
		const { buffers, attribute } = this;
		cycleBuffers(buffers);
		buffers[0] = padBuffer({
			device: this.device,
			buffer: buffers[0],
			attribute,
			fromLength: prevLength,
			toLength: this.currentLength,
			fromStartIndices: prevStartIndices,
			getData: transitionSettings.enter
		});
		buffers[1] = matchBuffer({
			device: this.device,
			source: buffers[0],
			target: buffers[1]
		});
		this.setBuffer(buffers[1]);
		const { transform } = this;
		const model = transform.model;
		let vertexCount = Math.floor(this.currentLength / attribute.size);
		if (useFp64(attribute)) vertexCount /= 2;
		model.setVertexCount(vertexCount);
		if (attribute.isConstant) {
			model.setAttributes({ aFrom: buffers[0] });
			model.setConstantAttributes({ aTo: attribute.value });
		} else model.setAttributes({
			aFrom: buffers[0],
			aTo: attribute.getBuffer()
		});
		transform.transformFeedback.setBuffers({ vCurrent: buffers[1] });
	}
	onUpdate() {
		const { duration, easing } = this.settings;
		const { time } = this.transition;
		let t = time / duration;
		if (easing) t = easing(t);
		const { model } = this.transform;
		const interpolationProps = { time: t };
		model.shaderInputs.setProps({ interpolation: interpolationProps });
		this.transform.run({ discard: true });
	}
	delete() {
		super.delete();
		this.transform.destroy();
	}
};
var interpolationUniforms = {
	name: "interpolation",
	vs: `\
layout(std140) uniform interpolationUniforms {
  float time;
} interpolation;
`,
	uniformTypes: { time: "f32" }
};
var vs$1 = `\
#version 300 es
#define SHADER_NAME interpolation-transition-vertex-shader

in ATTRIBUTE_TYPE aFrom;
in ATTRIBUTE_TYPE aTo;
out ATTRIBUTE_TYPE vCurrent;

void main(void) {
  vCurrent = mix(aFrom, aTo, interpolation.time);
  gl_Position = vec4(0.0);
}
`;
var vs64 = `\
#version 300 es
#define SHADER_NAME interpolation-transition-vertex-shader

in ATTRIBUTE_TYPE aFrom;
in ATTRIBUTE_TYPE aFrom64Low;
in ATTRIBUTE_TYPE aTo;
in ATTRIBUTE_TYPE aTo64Low;
out ATTRIBUTE_TYPE vCurrent;
out ATTRIBUTE_TYPE vCurrent64Low;

vec2 mix_fp64(vec2 a, vec2 b, float x) {
  vec2 range = sub_fp64(b, a);
  return sum_fp64(a, mul_fp64(range, vec2(x, 0.0)));
}

void main(void) {
  for (int i=0; i<ATTRIBUTE_SIZE; i++) {
    vec2 value = mix_fp64(vec2(aFrom[i], aFrom64Low[i]), vec2(aTo[i], aTo64Low[i]), interpolation.time);
    vCurrent[i] = value.x;
    vCurrent64Low[i] = value.y;
  }
  gl_Position = vec4(0.0);
}
`;
function useFp64(attribute) {
	return attribute.doublePrecision && attribute.value instanceof Float64Array;
}
function getTransform$1(device, attribute) {
	const attributeSize = attribute.size;
	const attributeType = getAttributeTypeFromSize(attributeSize);
	const inputFormat = getFloat32VertexFormat(attributeSize);
	const bufferLayout = attribute.getBufferLayout();
	if (useFp64(attribute)) return new BufferTransform(device, {
		vs: vs64,
		bufferLayout: [{
			name: "aFrom",
			byteStride: 8 * attributeSize,
			attributes: [{
				attribute: "aFrom",
				format: inputFormat,
				byteOffset: 0
			}, {
				attribute: "aFrom64Low",
				format: inputFormat,
				byteOffset: 4 * attributeSize
			}]
		}, {
			name: "aTo",
			byteStride: 8 * attributeSize,
			attributes: [{
				attribute: "aTo",
				format: inputFormat,
				byteOffset: 0
			}, {
				attribute: "aTo64Low",
				format: inputFormat,
				byteOffset: 4 * attributeSize
			}]
		}],
		modules: [fp64arithmetic, interpolationUniforms],
		defines: {
			ATTRIBUTE_TYPE: attributeType,
			ATTRIBUTE_SIZE: attributeSize
		},
		moduleSettings: {},
		varyings: ["vCurrent", "vCurrent64Low"],
		bufferMode: 35980,
		disableWarnings: true
	});
	return new BufferTransform(device, {
		vs: vs$1,
		bufferLayout: [{
			name: "aFrom",
			format: inputFormat
		}, {
			name: "aTo",
			format: bufferLayout.attributes[0].format
		}],
		modules: [interpolationUniforms],
		defines: { ATTRIBUTE_TYPE: attributeType },
		varyings: ["vCurrent"],
		disableWarnings: true
	});
}
//#endregion
//#region node_modules/@deck.gl/core/dist/transitions/gpu-spring-transition.js
var GPUSpringTransition = class extends GPUTransitionBase {
	constructor({ device, attribute, timeline }) {
		super({
			device,
			attribute,
			timeline
		});
		this.type = "spring";
		this.texture = getTexture(device);
		this.framebuffer = getFramebuffer(device, this.texture);
		this.transform = getTransform(device, attribute);
	}
	start(transitionSettings, numInstances) {
		const prevLength = this.currentLength;
		const prevStartIndices = this.currentStartIndices;
		super.start(transitionSettings, numInstances);
		const { buffers, attribute } = this;
		for (let i = 0; i < 2; i++) buffers[i] = padBuffer({
			device: this.device,
			buffer: buffers[i],
			attribute,
			fromLength: prevLength,
			toLength: this.currentLength,
			fromStartIndices: prevStartIndices,
			getData: transitionSettings.enter
		});
		buffers[2] = matchBuffer({
			device: this.device,
			source: buffers[0],
			target: buffers[2]
		});
		this.setBuffer(buffers[1]);
		const { model } = this.transform;
		model.setVertexCount(Math.floor(this.currentLength / attribute.size));
		if (attribute.isConstant) model.setConstantAttributes({ aTo: attribute.value });
		else model.setAttributes({ aTo: attribute.getBuffer() });
	}
	onUpdate() {
		const { buffers, transform, framebuffer, transition } = this;
		const settings = this.settings;
		transform.model.setAttributes({
			aPrev: buffers[0],
			aCur: buffers[1]
		});
		transform.transformFeedback.setBuffers({ vNext: buffers[2] });
		const springProps = {
			stiffness: settings.stiffness,
			damping: settings.damping
		};
		transform.model.shaderInputs.setProps({ spring: springProps });
		transform.run({
			framebuffer,
			discard: false,
			parameters: { viewport: [
				0,
				0,
				1,
				1
			] },
			clearColor: [
				0,
				0,
				0,
				0
			]
		});
		cycleBuffers(buffers);
		this.setBuffer(buffers[1]);
		if (!(this.device.readPixelsToArrayWebGL(framebuffer)[0] > 0)) transition.end();
	}
	delete() {
		super.delete();
		this.transform.destroy();
		this.texture.destroy();
		this.framebuffer.destroy();
	}
};
var springUniforms = {
	name: "spring",
	vs: `\
layout(std140) uniform springUniforms {
  float damping;
  float stiffness;
} spring;
`,
	uniformTypes: {
		damping: "f32",
		stiffness: "f32"
	}
};
var vs = `\
#version 300 es
#define SHADER_NAME spring-transition-vertex-shader

#define EPSILON 0.00001

in ATTRIBUTE_TYPE aPrev;
in ATTRIBUTE_TYPE aCur;
in ATTRIBUTE_TYPE aTo;
out ATTRIBUTE_TYPE vNext;
out float vIsTransitioningFlag;

ATTRIBUTE_TYPE getNextValue(ATTRIBUTE_TYPE cur, ATTRIBUTE_TYPE prev, ATTRIBUTE_TYPE dest) {
  ATTRIBUTE_TYPE velocity = cur - prev;
  ATTRIBUTE_TYPE delta = dest - cur;
  ATTRIBUTE_TYPE force = delta * spring.stiffness;
  ATTRIBUTE_TYPE resistance = velocity * spring.damping;
  return force - resistance + velocity + cur;
}

void main(void) {
  bool isTransitioning = length(aCur - aPrev) > EPSILON || length(aTo - aCur) > EPSILON;
  vIsTransitioningFlag = isTransitioning ? 1.0 : 0.0;

  vNext = getNextValue(aCur, aPrev, aTo);
  gl_Position = vec4(0, 0, 0, 1);
  gl_PointSize = 100.0;
}
`;
var fs = `\
#version 300 es
#define SHADER_NAME spring-transition-is-transitioning-fragment-shader

in float vIsTransitioningFlag;

out vec4 fragColor;

void main(void) {
  if (vIsTransitioningFlag == 0.0) {
    discard;
  }
  fragColor = vec4(1.0);
}`;
function getTransform(device, attribute) {
	const attributeType = getAttributeTypeFromSize(attribute.size);
	const format = getFloat32VertexFormat(attribute.size);
	return new BufferTransform(device, {
		vs,
		fs,
		bufferLayout: [
			{
				name: "aPrev",
				format
			},
			{
				name: "aCur",
				format
			},
			{
				name: "aTo",
				format: attribute.getBufferLayout().attributes[0].format
			}
		],
		varyings: ["vNext"],
		modules: [springUniforms],
		defines: { ATTRIBUTE_TYPE: attributeType },
		parameters: {
			depthCompare: "always",
			blendColorOperation: "max",
			blendColorSrcFactor: "one",
			blendColorDstFactor: "one",
			blendAlphaOperation: "max",
			blendAlphaSrcFactor: "one",
			blendAlphaDstFactor: "one"
		}
	});
}
function getTexture(device) {
	return device.createTexture({
		data: new Uint8Array(4),
		format: "rgba8unorm",
		width: 1,
		height: 1
	});
}
function getFramebuffer(device, texture) {
	return device.createFramebuffer({
		id: "spring-transition-is-transitioning-framebuffer",
		width: 1,
		height: 1,
		colorAttachments: [texture]
	});
}
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/attribute/attribute-transition-manager.js
var TRANSITION_TYPES$1 = {
	interpolation: GPUInterpolationTransition,
	spring: GPUSpringTransition
};
var AttributeTransitionManager = class {
	constructor(device, { id, timeline }) {
		if (!device) throw new Error("AttributeTransitionManager is constructed without device");
		this.id = id;
		this.device = device;
		this.timeline = timeline;
		this.transitions = {};
		this.needsRedraw = false;
		this.numInstances = 1;
	}
	finalize() {
		for (const attributeName in this.transitions) this._removeTransition(attributeName);
	}
	update({ attributes, transitions, numInstances }) {
		this.numInstances = numInstances || 1;
		for (const attributeName in attributes) {
			const attribute = attributes[attributeName];
			const settings = attribute.getTransitionSetting(transitions);
			if (!settings) continue;
			this._updateAttribute(attributeName, attribute, settings);
		}
		for (const attributeName in this.transitions) {
			const attribute = attributes[attributeName];
			if (!attribute || !attribute.getTransitionSetting(transitions)) this._removeTransition(attributeName);
		}
	}
	hasAttribute(attributeName) {
		const transition = this.transitions[attributeName];
		return transition && transition.inProgress;
	}
	getAttributes() {
		const animatedAttributes = {};
		for (const attributeName in this.transitions) {
			const transition = this.transitions[attributeName];
			if (transition.inProgress) animatedAttributes[attributeName] = transition.attributeInTransition;
		}
		return animatedAttributes;
	}
	run() {
		if (this.numInstances === 0) return false;
		for (const attributeName in this.transitions) if (this.transitions[attributeName].update()) this.needsRedraw = true;
		const needsRedraw = this.needsRedraw;
		this.needsRedraw = false;
		return needsRedraw;
	}
	_removeTransition(attributeName) {
		this.transitions[attributeName].delete();
		delete this.transitions[attributeName];
	}
	_updateAttribute(attributeName, attribute, settings) {
		const transition = this.transitions[attributeName];
		let isNew = !transition || transition.type !== settings.type;
		if (isNew) {
			if (transition) this._removeTransition(attributeName);
			const TransitionType = TRANSITION_TYPES$1[settings.type];
			if (TransitionType) this.transitions[attributeName] = new TransitionType({
				attribute,
				timeline: this.timeline,
				device: this.device
			});
			else {
				defaultLogger.error(`unsupported transition type '${settings.type}'`)();
				isNew = false;
			}
		}
		if (isNew || attribute.needsRedraw()) {
			this.needsRedraw = true;
			this.transitions[attributeName].start(settings, this.numInstances);
		}
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/attribute/attribute-manager.js
var TRACE_INVALIDATE = "attributeManager.invalidate";
var TRACE_UPDATE_START = "attributeManager.updateStart";
var TRACE_UPDATE_END = "attributeManager.updateEnd";
var TRACE_ATTRIBUTE_UPDATE_START = "attribute.updateStart";
var TRACE_ATTRIBUTE_ALLOCATE = "attribute.allocate";
var TRACE_ATTRIBUTE_UPDATE_END = "attribute.updateEnd";
var AttributeManager = class {
	constructor(device, { id = "attribute-manager", stats, timeline } = {}) {
		this.mergeBoundsMemoized = memoize(mergeBounds);
		this.id = id;
		this.device = device;
		this.attributes = {};
		this.updateTriggers = {};
		this.needsRedraw = true;
		this.userData = {};
		this.stats = stats;
		this.attributeTransitionManager = new AttributeTransitionManager(device, {
			id: `${id}-transitions`,
			timeline
		});
		Object.seal(this);
	}
	finalize() {
		for (const attributeName in this.attributes) this.attributes[attributeName].delete();
		this.attributeTransitionManager.finalize();
	}
	getNeedsRedraw(opts = { clearRedrawFlags: false }) {
		const redraw = this.needsRedraw;
		this.needsRedraw = this.needsRedraw && !opts.clearRedrawFlags;
		return redraw && this.id;
	}
	setNeedsRedraw() {
		this.needsRedraw = true;
	}
	add(attributes) {
		this._add(attributes);
	}
	addInstanced(attributes) {
		this._add(attributes, { stepMode: "instance" });
	}
	/**
	* Removes attributes
	* Takes an array of attribute names and delete them from
	* the attribute map if they exists
	*
	* @example
	* attributeManager.remove(['position']);
	*
	* @param {Object} attributeNameArray - attribute name array (see above)
	*/
	remove(attributeNameArray) {
		for (const name of attributeNameArray) if (this.attributes[name] !== void 0) {
			this.attributes[name].delete();
			delete this.attributes[name];
		}
	}
	invalidate(triggerName, dataRange) {
		const invalidatedAttributes = this._invalidateTrigger(triggerName, dataRange);
		debug(TRACE_INVALIDATE, this, triggerName, invalidatedAttributes);
	}
	invalidateAll(dataRange) {
		for (const attributeName in this.attributes) this.attributes[attributeName].setNeedsUpdate(attributeName, dataRange);
		debug(TRACE_INVALIDATE, this, "all");
	}
	update({ data, numInstances, startIndices = null, transitions, props = {}, buffers = {}, context = {} }) {
		let updated = false;
		debug(TRACE_UPDATE_START, this);
		if (this.stats) this.stats.get("Update Attributes").timeStart();
		for (const attributeName in this.attributes) {
			const attribute = this.attributes[attributeName];
			const accessorName = attribute.settings.accessor;
			attribute.startIndices = startIndices;
			attribute.numInstances = numInstances;
			if (props[attributeName]) defaultLogger.removed(`props.${attributeName}`, `data.attributes.${attributeName}`)();
			if (attribute.setExternalBuffer(buffers[attributeName])) {} else if (attribute.setBinaryValue(typeof accessorName === "string" ? buffers[accessorName] : void 0, data.startIndices)) {} else if (typeof accessorName === "string" && !buffers[accessorName] && attribute.setConstantValue(context, props[accessorName])) {} else if (attribute.needsUpdate()) {
				updated = true;
				this._updateAttribute({
					attribute,
					numInstances,
					data,
					props,
					context
				});
			}
			this.needsRedraw = this.needsRedraw || attribute.needsRedraw();
		}
		if (updated) debug(TRACE_UPDATE_END, this, numInstances);
		if (this.stats) {
			this.stats.get("Update Attributes").timeEnd();
			if (updated) this.stats.get("Attributes updated").incrementCount();
		}
		this.attributeTransitionManager.update({
			attributes: this.attributes,
			numInstances,
			transitions
		});
	}
	updateTransition() {
		const { attributeTransitionManager } = this;
		const transitionUpdated = attributeTransitionManager.run();
		this.needsRedraw = this.needsRedraw || transitionUpdated;
		return transitionUpdated;
	}
	/**
	* Returns all attribute descriptors
	* Note: Format matches luma.gl Model/Program.setAttributes()
	* @return {Object} attributes - descriptors
	*/
	getAttributes() {
		return {
			...this.attributes,
			...this.attributeTransitionManager.getAttributes()
		};
	}
	/**
	* Computes the spatial bounds of a given set of attributes
	*/
	getBounds(attributeNames) {
		const bounds = attributeNames.map((attributeName) => this.attributes[attributeName]?.getBounds());
		return this.mergeBoundsMemoized(bounds);
	}
	/**
	* Returns changed attribute descriptors
	* This indicates which WebGLBuffers need to be updated
	* @return {Object} attributes - descriptors
	*/
	getChangedAttributes(opts = { clearChangedFlags: false }) {
		const { attributes, attributeTransitionManager } = this;
		const changedAttributes = { ...attributeTransitionManager.getAttributes() };
		for (const attributeName in attributes) {
			const attribute = attributes[attributeName];
			if (attribute.needsRedraw(opts) && !attributeTransitionManager.hasAttribute(attributeName)) changedAttributes[attributeName] = attribute;
		}
		return changedAttributes;
	}
	/** Generate WebGPU-style buffer layout descriptors from all attributes */
	getBufferLayouts(modelInfo) {
		return Object.values(this.getAttributes()).map((attribute) => attribute.getBufferLayout(modelInfo));
	}
	/** Register new attributes */
	_add(attributes, overrideOptions) {
		for (const attributeName in attributes) {
			const attribute = attributes[attributeName];
			const props = {
				...attribute,
				id: attributeName,
				size: attribute.isIndexed && 1 || attribute.size || 1,
				...overrideOptions
			};
			this.attributes[attributeName] = new Attribute(this.device, props);
		}
		this._mapUpdateTriggersToAttributes();
	}
	_mapUpdateTriggersToAttributes() {
		const triggers = {};
		for (const attributeName in this.attributes) this.attributes[attributeName].getUpdateTriggers().forEach((triggerName) => {
			if (!triggers[triggerName]) triggers[triggerName] = [];
			triggers[triggerName].push(attributeName);
		});
		this.updateTriggers = triggers;
	}
	_invalidateTrigger(triggerName, dataRange) {
		const { attributes, updateTriggers } = this;
		const invalidatedAttributes = updateTriggers[triggerName];
		if (invalidatedAttributes) invalidatedAttributes.forEach((name) => {
			const attribute = attributes[name];
			if (attribute) attribute.setNeedsUpdate(attribute.id, dataRange);
		});
		return invalidatedAttributes;
	}
	_updateAttribute(opts) {
		const { attribute, numInstances } = opts;
		debug(TRACE_ATTRIBUTE_UPDATE_START, attribute);
		if (attribute.constant) {
			attribute.setConstantValue(opts.context, attribute.value);
			return;
		}
		if (attribute.allocate(numInstances)) debug(TRACE_ATTRIBUTE_ALLOCATE, attribute, numInstances);
		if (attribute.updateBuffer(opts)) {
			this.needsRedraw = true;
			debug(TRACE_ATTRIBUTE_UPDATE_END, attribute, numInstances);
		}
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/transitions/cpu-interpolation-transition.js
var CPUInterpolationTransition = class extends Transition {
	get value() {
		return this._value;
	}
	_onUpdate() {
		const { time, settings: { fromValue, toValue, duration, easing } } = this;
		const t = easing(time / duration);
		this._value = lerp(fromValue, toValue, t);
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/transitions/cpu-spring-transition.js
var EPSILON = 1e-5;
function updateSpringElement(prev, cur, dest, damping, stiffness) {
	const velocity = cur - prev;
	return (dest - cur) * stiffness + -velocity * damping + velocity + cur;
}
function updateSpring(prev, cur, dest, damping, stiffness) {
	if (Array.isArray(dest)) {
		const next = [];
		for (let i = 0; i < dest.length; i++) next[i] = updateSpringElement(prev[i], cur[i], dest[i], damping, stiffness);
		return next;
	}
	return updateSpringElement(prev, cur, dest, damping, stiffness);
}
function distance(value1, value2) {
	if (Array.isArray(value1)) {
		let distanceSquare = 0;
		for (let i = 0; i < value1.length; i++) {
			const d = value1[i] - value2[i];
			distanceSquare += d * d;
		}
		return Math.sqrt(distanceSquare);
	}
	return Math.abs(value1 - value2);
}
var CPUSpringTransition = class extends Transition {
	get value() {
		return this._currValue;
	}
	_onUpdate() {
		const { fromValue, toValue, damping, stiffness } = this.settings;
		const { _prevValue = fromValue, _currValue = fromValue } = this;
		let nextValue = updateSpring(_prevValue, _currValue, toValue, damping, stiffness);
		const delta = distance(nextValue, toValue);
		const velocity = distance(nextValue, _currValue);
		if (delta < EPSILON && velocity < EPSILON) {
			nextValue = toValue;
			this.end();
		}
		this._prevValue = _currValue;
		this._currValue = nextValue;
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/uniform-transition-manager.js
var TRANSITION_TYPES = {
	interpolation: CPUInterpolationTransition,
	spring: CPUSpringTransition
};
var UniformTransitionManager = class {
	constructor(timeline) {
		this.transitions = /* @__PURE__ */ new Map();
		this.timeline = timeline;
	}
	get active() {
		return this.transitions.size > 0;
	}
	add(key, fromValue, toValue, settings) {
		const { transitions } = this;
		if (transitions.has(key)) {
			const transition = transitions.get(key);
			const { value = transition.settings.fromValue } = transition;
			fromValue = value;
			this.remove(key);
		}
		settings = normalizeTransitionSettings(settings);
		if (!settings) return;
		const TransitionType = TRANSITION_TYPES[settings.type];
		if (!TransitionType) {
			defaultLogger.error(`unsupported transition type '${settings.type}'`)();
			return;
		}
		const transition = new TransitionType(this.timeline);
		transition.start({
			...settings,
			fromValue,
			toValue
		});
		transitions.set(key, transition);
	}
	remove(key) {
		const { transitions } = this;
		if (transitions.has(key)) {
			transitions.get(key).cancel();
			transitions.delete(key);
		}
	}
	update() {
		const propsInTransition = {};
		for (const [key, transition] of this.transitions) {
			transition.update();
			propsInTransition[key] = transition.value;
			if (!transition.inProgress) this.remove(key);
		}
		return propsInTransition;
	}
	clear() {
		for (const key of this.transitions.keys()) this.remove(key);
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/lifecycle/props.js
function validateProps(props) {
	const propTypes = props[PROP_TYPES_SYMBOL];
	for (const propName in propTypes) {
		const propType = propTypes[propName];
		const { validate } = propType;
		if (validate && !validate(props[propName], propType)) throw new Error(`Invalid prop ${propName}: ${props[propName]}`);
	}
}
function diffProps(props, oldProps) {
	const propsChangedReason = compareProps({
		newProps: props,
		oldProps,
		propTypes: props[PROP_TYPES_SYMBOL],
		ignoreProps: {
			data: null,
			updateTriggers: null,
			extensions: null,
			transitions: null
		}
	});
	const dataChangedReason = diffDataProps(props, oldProps);
	let updateTriggersChangedReason = false;
	if (!dataChangedReason) updateTriggersChangedReason = diffUpdateTriggers(props, oldProps);
	return {
		dataChanged: dataChangedReason,
		propsChanged: propsChangedReason,
		updateTriggersChanged: updateTriggersChangedReason,
		extensionsChanged: diffExtensions(props, oldProps),
		transitionsChanged: diffTransitions(props, oldProps)
	};
}
function diffTransitions(props, oldProps) {
	if (!props.transitions) return false;
	const result = {};
	const propTypes = props[PROP_TYPES_SYMBOL];
	let changed = false;
	for (const key in props.transitions) {
		const propType = propTypes[key];
		const type = propType && propType.type;
		if ((type === "number" || type === "color" || type === "array") && comparePropValues(props[key], oldProps[key], propType)) {
			result[key] = true;
			changed = true;
		}
	}
	return changed ? result : false;
}
/**
* Performs equality by iterating through keys on an object and returning false
* when any key has values which are not strictly equal between the arguments.
* @param {Object} opt.oldProps - object with old key/value pairs
* @param {Object} opt.newProps - object with new key/value pairs
* @param {Object} opt.ignoreProps={} - object, keys that should not be compared
* @returns {null|String} - null when values of all keys are strictly equal.
*   if unequal, returns a string explaining what changed.
*/
function compareProps({ newProps, oldProps, ignoreProps = {}, propTypes = {}, triggerName = "props" }) {
	if (oldProps === newProps) return false;
	if (typeof newProps !== "object" || newProps === null) return `${triggerName} changed shallowly`;
	if (typeof oldProps !== "object" || oldProps === null) return `${triggerName} changed shallowly`;
	for (const key of Object.keys(newProps)) if (!(key in ignoreProps)) {
		if (!(key in oldProps)) return `${triggerName}.${key} added`;
		const changed = comparePropValues(newProps[key], oldProps[key], propTypes[key]);
		if (changed) return `${triggerName}.${key} ${changed}`;
	}
	for (const key of Object.keys(oldProps)) if (!(key in ignoreProps)) {
		if (!(key in newProps)) return `${triggerName}.${key} dropped`;
		if (!Object.hasOwnProperty.call(newProps, key)) {
			const changed = comparePropValues(newProps[key], oldProps[key], propTypes[key]);
			if (changed) return `${triggerName}.${key} ${changed}`;
		}
	}
	return false;
}
function comparePropValues(newProp, oldProp, propType) {
	let equal = propType && propType.equal;
	if (equal && !equal(newProp, oldProp, propType)) return "changed deeply";
	if (!equal) {
		equal = newProp && oldProp && newProp.equals;
		if (equal && !equal.call(newProp, oldProp)) return "changed deeply";
	}
	if (!equal && oldProp !== newProp) return "changed shallowly";
	return null;
}
function diffDataProps(props, oldProps) {
	if (oldProps === null) return "oldProps is null, initial diff";
	let dataChanged = false;
	const { dataComparator, _dataDiff } = props;
	if (dataComparator) {
		if (!dataComparator(props.data, oldProps.data)) dataChanged = "Data comparator detected a change";
	} else if (props.data !== oldProps.data) dataChanged = "A new data container was supplied";
	if (dataChanged && _dataDiff) dataChanged = _dataDiff(props.data, oldProps.data) || dataChanged;
	return dataChanged;
}
function diffUpdateTriggers(props, oldProps) {
	if (oldProps === null) return { all: true };
	if ("all" in props.updateTriggers) {
		if (diffUpdateTrigger(props, oldProps, "all")) return { all: true };
	}
	const reason = {};
	let changed = false;
	for (const triggerName in props.updateTriggers) if (triggerName !== "all") {
		if (diffUpdateTrigger(props, oldProps, triggerName)) {
			reason[triggerName] = true;
			changed = true;
		}
	}
	return changed ? reason : false;
}
function diffExtensions(props, oldProps) {
	if (oldProps === null) return true;
	const oldExtensions = oldProps.extensions;
	const { extensions } = props;
	if (extensions === oldExtensions) return false;
	if (!oldExtensions || !extensions) return true;
	if (extensions.length !== oldExtensions.length) return true;
	for (let i = 0; i < extensions.length; i++) if (!extensions[i].equals(oldExtensions[i])) return true;
	return false;
}
function diffUpdateTrigger(props, oldProps, triggerName) {
	let newTriggers = props.updateTriggers[triggerName];
	newTriggers = newTriggers === void 0 || newTriggers === null ? {} : newTriggers;
	let oldTriggers = oldProps.updateTriggers[triggerName];
	oldTriggers = oldTriggers === void 0 || oldTriggers === null ? {} : oldTriggers;
	return compareProps({
		oldProps: oldTriggers,
		newProps: newTriggers,
		triggerName
	});
}
//#endregion
//#region node_modules/@deck.gl/core/dist/utils/count.js
var ERR_NOT_OBJECT = "count(): argument not an object";
var ERR_NOT_CONTAINER = "count(): argument not a container";
/**
* Deduces numer of elements in a JavaScript container.
* - Auto-deduction for ES6 containers that define a count() method
* - Auto-deduction for ES6 containers that define a size member
* - Auto-deduction for Classic Arrays via the built-in length attribute
* - Also handles objects, although note that this an O(N) operation
*/
function count(container) {
	if (!isObject(container)) throw new Error(ERR_NOT_OBJECT);
	if (typeof container.count === "function") return container.count();
	if (Number.isFinite(container.size)) return container.size;
	if (Number.isFinite(container.length)) return container.length;
	if (isPlainObject(container)) return Object.keys(container).length;
	throw new Error(ERR_NOT_CONTAINER);
}
/**
* Checks if argument is a plain object (not a class or array etc)
* @param {*} value - JavaScript value to be tested
* @return {Boolean} - true if argument is a plain JavaScript object
*/
function isPlainObject(value) {
	return value !== null && typeof value === "object" && value.constructor === Object;
}
/**
* Checks if argument is an indexable object (not a primitive value, nor null)
* @param {*} value - JavaScript value to be tested
* @return {Boolean} - true if argument is a JavaScript object
*/
function isObject(value) {
	return value !== null && typeof value === "object";
}
//#endregion
//#region node_modules/@deck.gl/core/dist/utils/shader.js
function mergeShaders(target, source) {
	if (!source) return target;
	const result = {
		...target,
		...source
	};
	if ("defines" in source) result.defines = {
		...target.defines,
		...source.defines
	};
	if ("modules" in source) {
		result.modules = (target.modules || []).concat(source.modules);
		if (source.modules.some((module) => module.name === "project64")) {
			const index = result.modules.findIndex((module) => module.name === "project32");
			if (index >= 0) result.modules.splice(index, 1);
		}
	}
	if ("inject" in source) if (!target.inject) result.inject = source.inject;
	else {
		const mergedInjection = { ...target.inject };
		for (const key in source.inject) mergedInjection[key] = (mergedInjection[key] || "") + source.inject[key];
		result.inject = mergedInjection;
	}
	return result;
}
//#endregion
//#region node_modules/@deck.gl/core/dist/utils/texture.js
var DEFAULT_TEXTURE_PARAMETERS = {
	minFilter: "linear",
	mipmapFilter: "linear",
	magFilter: "linear",
	addressModeU: "clamp-to-edge",
	addressModeV: "clamp-to-edge"
};
var internalTextures = {};
/**
*
* @param owner
* @param device
* @param image could be one of:
*   - Texture
*   - Browser object: Image, ImageData, ImageData, HTMLCanvasElement, HTMLVideoElement, ImageBitmap
*   - Plain object: {width: <number>, height: <number>, data: <Uint8Array>}
* @param parameters
* @returns
*/
function createTexture(owner, device, image, sampler) {
	if (image instanceof Texture) return image;
	else if (image.constructor && image.constructor.name !== "Object") image = { data: image };
	let samplerParameters = null;
	if (image.compressed) samplerParameters = {
		minFilter: "linear",
		mipmapFilter: image.data.length > 1 ? "nearest" : "linear"
	};
	const { width, height } = image.data;
	const texture = device.createTexture({
		...image,
		sampler: {
			...DEFAULT_TEXTURE_PARAMETERS,
			...samplerParameters,
			...sampler
		},
		mipLevels: device.getMipLevelCount(width, height)
	});
	if (device.type === "webgl") texture.generateMipmapsWebGL();
	else if (device.type === "webgpu") device.generateMipmapsWebGPU(texture);
	internalTextures[texture.id] = owner;
	return texture;
}
function destroyTexture(owner, texture) {
	if (!texture || !(texture instanceof Texture)) return;
	if (internalTextures[texture.id] === owner) {
		texture.delete();
		delete internalTextures[texture.id];
	}
}
//#endregion
//#region node_modules/@deck.gl/core/dist/lifecycle/prop-types.js
var TYPE_DEFINITIONS = {
	boolean: {
		validate(value, propType) {
			return true;
		},
		equal(value1, value2, propType) {
			return Boolean(value1) === Boolean(value2);
		}
	},
	number: { validate(value, propType) {
		return Number.isFinite(value) && (!("max" in propType) || value <= propType.max) && (!("min" in propType) || value >= propType.min);
	} },
	color: {
		validate(value, propType) {
			return propType.optional && !value || isArray(value) && (value.length === 3 || value.length === 4);
		},
		equal(value1, value2, propType) {
			return deepEqual$1(value1, value2, 1);
		}
	},
	accessor: {
		validate(value, propType) {
			const valueType = getTypeOf(value);
			return valueType === "function" || valueType === getTypeOf(propType.value);
		},
		equal(value1, value2, propType) {
			if (typeof value2 === "function") return true;
			return deepEqual$1(value1, value2, 1);
		}
	},
	array: {
		validate(value, propType) {
			return propType.optional && !value || isArray(value);
		},
		equal(value1, value2, propType) {
			const { compare } = propType;
			return compare ? deepEqual$1(value1, value2, Number.isInteger(compare) ? compare : compare ? 1 : 0) : value1 === value2;
		}
	},
	object: { equal(value1, value2, propType) {
		if (propType.ignore) return true;
		const { compare } = propType;
		return compare ? deepEqual$1(value1, value2, Number.isInteger(compare) ? compare : compare ? 1 : 0) : value1 === value2;
	} },
	function: {
		validate(value, propType) {
			return propType.optional && !value || typeof value === "function";
		},
		equal(value1, value2, propType) {
			return !propType.compare && propType.ignore !== false || value1 === value2;
		}
	},
	data: { transform: (value, propType, component) => {
		if (!value) return value;
		const { dataTransform } = component.props;
		if (dataTransform) return dataTransform(value);
		if (typeof value.shape === "string" && value.shape.endsWith("-table") && Array.isArray(value.data)) return value.data;
		return value;
	} },
	image: {
		transform: (value, propType, component) => {
			const context = component.context;
			if (!context || !context.device) return null;
			return createTexture(component.id, context.device, value, {
				...propType.parameters,
				...component.props.textureParameters
			});
		},
		release: (value, propType, component) => {
			destroyTexture(component.id, value);
		}
	}
};
function parsePropTypes(propDefs) {
	const propTypes = {};
	const defaultProps = {};
	const deprecatedProps = {};
	for (const [propName, propDef] of Object.entries(propDefs)) {
		const deprecated = propDef?.deprecatedFor;
		if (deprecated) deprecatedProps[propName] = Array.isArray(deprecated) ? deprecated : [deprecated];
		else {
			const propType = parsePropType(propName, propDef);
			propTypes[propName] = propType;
			defaultProps[propName] = propType.value;
		}
	}
	return {
		propTypes,
		defaultProps,
		deprecatedProps
	};
}
function parsePropType(name, propDef) {
	switch (getTypeOf(propDef)) {
		case "object": return normalizePropDefinition(name, propDef);
		case "array": return normalizePropDefinition(name, {
			type: "array",
			value: propDef,
			compare: false
		});
		case "boolean": return normalizePropDefinition(name, {
			type: "boolean",
			value: propDef
		});
		case "number": return normalizePropDefinition(name, {
			type: "number",
			value: propDef
		});
		case "function": return normalizePropDefinition(name, {
			type: "function",
			value: propDef,
			compare: true
		});
		default: return {
			name,
			type: "unknown",
			value: propDef
		};
	}
}
function normalizePropDefinition(name, propDef) {
	if (!("type" in propDef)) {
		if (!("value" in propDef)) return {
			name,
			type: "object",
			value: propDef
		};
		return {
			name,
			type: getTypeOf(propDef.value),
			...propDef
		};
	}
	return {
		name,
		...TYPE_DEFINITIONS[propDef.type],
		...propDef
	};
}
function isArray(value) {
	return Array.isArray(value) || ArrayBuffer.isView(value);
}
function getTypeOf(value) {
	if (isArray(value)) return "array";
	if (value === null) return "null";
	return typeof value;
}
//#endregion
//#region node_modules/@deck.gl/core/dist/lifecycle/create-props.js
function createProps(component, propObjects) {
	let extensions;
	for (let i = propObjects.length - 1; i >= 0; i--) {
		const props = propObjects[i];
		if ("extensions" in props) extensions = props.extensions;
	}
	const propsPrototype = getPropsPrototype(component.constructor, extensions);
	const propsInstance = Object.create(propsPrototype);
	propsInstance[COMPONENT_SYMBOL] = component;
	propsInstance[ASYNC_ORIGINAL_SYMBOL] = {};
	propsInstance[ASYNC_RESOLVED_SYMBOL] = {};
	for (let i = 0; i < propObjects.length; ++i) {
		const props = propObjects[i];
		for (const key in props) propsInstance[key] = props[key];
	}
	Object.freeze(propsInstance);
	return propsInstance;
}
var MergedDefaultPropsCacheKey = "_mergedDefaultProps";
function getPropsPrototype(componentClass, extensions) {
	if (!(componentClass instanceof Component.constructor)) return {};
	let cacheKey = MergedDefaultPropsCacheKey;
	if (extensions) for (const extension of extensions) {
		const ExtensionClass = extension.constructor;
		if (ExtensionClass) cacheKey += `:${ExtensionClass.extensionName || ExtensionClass.name}`;
	}
	const defaultProps = getOwnProperty(componentClass, cacheKey);
	if (!defaultProps) return componentClass[cacheKey] = createPropsPrototypeAndTypes(componentClass, extensions || []);
	return defaultProps;
}
function createPropsPrototypeAndTypes(componentClass, extensions) {
	if (!componentClass.prototype) return null;
	const parentDefaultProps = getPropsPrototype(Object.getPrototypeOf(componentClass));
	const componentPropDefs = parsePropTypes(getOwnProperty(componentClass, "defaultProps") || {});
	const defaultProps = Object.assign(Object.create(null), parentDefaultProps, componentPropDefs.defaultProps);
	const propTypes = Object.assign(Object.create(null), parentDefaultProps?.[PROP_TYPES_SYMBOL], componentPropDefs.propTypes);
	const deprecatedProps = Object.assign(Object.create(null), parentDefaultProps?.[DEPRECATED_PROPS_SYMBOL], componentPropDefs.deprecatedProps);
	for (const extension of extensions) {
		const extensionDefaultProps = getPropsPrototype(extension.constructor);
		if (extensionDefaultProps) {
			Object.assign(defaultProps, extensionDefaultProps);
			Object.assign(propTypes, extensionDefaultProps[PROP_TYPES_SYMBOL]);
			Object.assign(deprecatedProps, extensionDefaultProps[DEPRECATED_PROPS_SYMBOL]);
		}
	}
	createPropsPrototype(defaultProps, componentClass);
	addAsyncPropsToPropPrototype(defaultProps, propTypes);
	addDeprecatedPropsToPropPrototype(defaultProps, deprecatedProps);
	defaultProps[PROP_TYPES_SYMBOL] = propTypes;
	defaultProps[DEPRECATED_PROPS_SYMBOL] = deprecatedProps;
	if (extensions.length === 0 && !hasOwnProperty(componentClass, "_propTypes")) componentClass._propTypes = propTypes;
	return defaultProps;
}
function createPropsPrototype(defaultProps, componentClass) {
	const id = getComponentName(componentClass);
	Object.defineProperties(defaultProps, { id: {
		writable: true,
		value: id
	} });
}
function addDeprecatedPropsToPropPrototype(defaultProps, deprecatedProps) {
	for (const propName in deprecatedProps) Object.defineProperty(defaultProps, propName, {
		enumerable: false,
		set(newValue) {
			const nameStr = `${this.id}: ${propName}`;
			for (const newPropName of deprecatedProps[propName]) if (!hasOwnProperty(this, newPropName)) this[newPropName] = newValue;
			defaultLogger.deprecated(nameStr, deprecatedProps[propName].join("/"))();
		}
	});
}
function addAsyncPropsToPropPrototype(defaultProps, propTypes) {
	const defaultValues = {};
	const descriptors = {};
	for (const propName in propTypes) {
		const propType = propTypes[propName];
		const { name, value } = propType;
		if (propType.async) {
			defaultValues[name] = value;
			descriptors[name] = getDescriptorForAsyncProp(name);
		}
	}
	defaultProps[ASYNC_DEFAULTS_SYMBOL] = defaultValues;
	defaultProps[ASYNC_ORIGINAL_SYMBOL] = {};
	Object.defineProperties(defaultProps, descriptors);
}
function getDescriptorForAsyncProp(name) {
	return {
		enumerable: true,
		set(newValue) {
			if (typeof newValue === "string" || newValue instanceof Promise || isAsyncIterable(newValue)) this[ASYNC_ORIGINAL_SYMBOL][name] = newValue;
			else this[ASYNC_RESOLVED_SYMBOL][name] = newValue;
		},
		get() {
			if (this[ASYNC_RESOLVED_SYMBOL]) {
				if (name in this[ASYNC_RESOLVED_SYMBOL]) return this[ASYNC_RESOLVED_SYMBOL][name] || this[ASYNC_DEFAULTS_SYMBOL][name];
				if (name in this[ASYNC_ORIGINAL_SYMBOL]) {
					const state = this[COMPONENT_SYMBOL] && this[COMPONENT_SYMBOL].internalState;
					if (state && state.hasAsyncProp(name)) return state.getAsyncProp(name) || this[ASYNC_DEFAULTS_SYMBOL][name];
				}
			}
			return this[ASYNC_DEFAULTS_SYMBOL][name];
		}
	};
}
function hasOwnProperty(object, prop) {
	return Object.prototype.hasOwnProperty.call(object, prop);
}
function getOwnProperty(object, prop) {
	return hasOwnProperty(object, prop) && object[prop];
}
function getComponentName(componentClass) {
	const componentName = componentClass.componentName;
	if (!componentName) defaultLogger.warn(`${componentClass.name}.componentName not specified`)();
	return componentName || componentClass.name;
}
//#endregion
//#region node_modules/@deck.gl/core/dist/lifecycle/component.js
var counter = 0;
var Component = class {
	constructor(...propObjects) {
		this.props = createProps(this, propObjects);
		this.id = this.props.id;
		this.count = counter++;
	}
	clone(newProps) {
		const { props } = this;
		const asyncProps = {};
		for (const key in props[ASYNC_DEFAULTS_SYMBOL]) if (key in props[ASYNC_RESOLVED_SYMBOL]) asyncProps[key] = props[ASYNC_RESOLVED_SYMBOL][key];
		else if (key in props[ASYNC_ORIGINAL_SYMBOL]) asyncProps[key] = props[ASYNC_ORIGINAL_SYMBOL][key];
		return new this.constructor({
			...props,
			...asyncProps,
			...newProps
		});
	}
};
Component.componentName = "Component";
Component.defaultProps = {};
//#endregion
//#region node_modules/@deck.gl/core/dist/lifecycle/component-state.js
var EMPTY_PROPS = Object.freeze({});
var ComponentState = class {
	constructor(component) {
		this.component = component;
		this.asyncProps = {};
		this.onAsyncPropUpdated = () => {};
		this.oldProps = null;
		this.oldAsyncProps = null;
	}
	finalize() {
		for (const propName in this.asyncProps) {
			const asyncProp = this.asyncProps[propName];
			if (asyncProp && asyncProp.type && asyncProp.type.release) asyncProp.type.release(asyncProp.resolvedValue, asyncProp.type, this.component);
		}
		this.asyncProps = {};
		this.component = null;
		this.resetOldProps();
	}
	getOldProps() {
		return this.oldAsyncProps || this.oldProps || EMPTY_PROPS;
	}
	resetOldProps() {
		this.oldAsyncProps = null;
		this.oldProps = this.component ? this.component.props : null;
	}
	hasAsyncProp(propName) {
		return propName in this.asyncProps;
	}
	getAsyncProp(propName) {
		const asyncProp = this.asyncProps[propName];
		return asyncProp && asyncProp.resolvedValue;
	}
	isAsyncPropLoading(propName) {
		if (propName) {
			const asyncProp = this.asyncProps[propName];
			return Boolean(asyncProp && asyncProp.pendingLoadCount > 0 && asyncProp.pendingLoadCount !== asyncProp.resolvedLoadCount);
		}
		for (const key in this.asyncProps) if (this.isAsyncPropLoading(key)) return true;
		return false;
	}
	reloadAsyncProp(propName, value) {
		this._watchPromise(propName, Promise.resolve(value));
	}
	setAsyncProps(props) {
		this.component = props[COMPONENT_SYMBOL] || this.component;
		const resolvedValues = props[ASYNC_RESOLVED_SYMBOL] || {};
		const originalValues = props[ASYNC_ORIGINAL_SYMBOL] || props;
		const defaultValues = props[ASYNC_DEFAULTS_SYMBOL] || {};
		for (const propName in resolvedValues) {
			const value = resolvedValues[propName];
			this._createAsyncPropData(propName, defaultValues[propName]);
			this._updateAsyncProp(propName, value);
			resolvedValues[propName] = this.getAsyncProp(propName);
		}
		for (const propName in originalValues) {
			const value = originalValues[propName];
			this._createAsyncPropData(propName, defaultValues[propName]);
			this._updateAsyncProp(propName, value);
		}
	}
	_fetch(propName, url) {
		return null;
	}
	_onResolve(propName, value) {}
	_onError(propName, error) {}
	_updateAsyncProp(propName, value) {
		if (!this._didAsyncInputValueChange(propName, value)) return;
		if (typeof value === "string") value = this._fetch(propName, value);
		if (value instanceof Promise) {
			this._watchPromise(propName, value);
			return;
		}
		if (isAsyncIterable(value)) {
			this._resolveAsyncIterable(propName, value);
			return;
		}
		this._setPropValue(propName, value);
	}
	_freezeAsyncOldProps() {
		if (!this.oldAsyncProps && this.oldProps) {
			this.oldAsyncProps = Object.create(this.oldProps);
			for (const propName in this.asyncProps) Object.defineProperty(this.oldAsyncProps, propName, {
				enumerable: true,
				value: this.oldProps[propName]
			});
		}
	}
	_didAsyncInputValueChange(propName, value) {
		const asyncProp = this.asyncProps[propName];
		if (value === asyncProp.resolvedValue || value === asyncProp.lastValue) return false;
		asyncProp.lastValue = value;
		return true;
	}
	_setPropValue(propName, value) {
		this._freezeAsyncOldProps();
		const asyncProp = this.asyncProps[propName];
		if (asyncProp) {
			value = this._postProcessValue(asyncProp, value);
			asyncProp.resolvedValue = value;
			asyncProp.pendingLoadCount++;
			asyncProp.resolvedLoadCount = asyncProp.pendingLoadCount;
		}
	}
	_setAsyncPropValue(propName, value, loadCount) {
		const asyncProp = this.asyncProps[propName];
		if (asyncProp && loadCount >= asyncProp.resolvedLoadCount && value !== void 0) {
			this._freezeAsyncOldProps();
			asyncProp.resolvedValue = value;
			asyncProp.resolvedLoadCount = loadCount;
			this.onAsyncPropUpdated(propName, value);
		}
	}
	_watchPromise(propName, promise) {
		const asyncProp = this.asyncProps[propName];
		if (asyncProp) {
			asyncProp.pendingLoadCount++;
			const loadCount = asyncProp.pendingLoadCount;
			promise.then((data) => {
				if (!this.component) return;
				data = this._postProcessValue(asyncProp, data);
				this._setAsyncPropValue(propName, data, loadCount);
				this._onResolve(propName, data);
			}).catch((error) => {
				this._onError(propName, error);
			});
		}
	}
	async _resolveAsyncIterable(propName, iterable) {
		if (propName !== "data") {
			this._setPropValue(propName, iterable);
			return;
		}
		const asyncProp = this.asyncProps[propName];
		if (!asyncProp) return;
		asyncProp.pendingLoadCount++;
		const loadCount = asyncProp.pendingLoadCount;
		let data = [];
		let count = 0;
		for await (const chunk of iterable) {
			if (!this.component) return;
			const { dataTransform } = this.component.props;
			if (dataTransform) data = dataTransform(chunk, data);
			else data = data.concat(chunk);
			Object.defineProperty(data, "__diff", {
				enumerable: false,
				value: [{
					startRow: count,
					endRow: data.length
				}]
			});
			count = data.length;
			this._setAsyncPropValue(propName, data, loadCount);
		}
		this._onResolve(propName, data);
	}
	_postProcessValue(asyncProp, value) {
		const propType = asyncProp.type;
		if (propType && this.component) {
			if (propType.release) propType.release(asyncProp.resolvedValue, propType, this.component);
			if (propType.transform) return propType.transform(value, propType, this.component);
		}
		return value;
	}
	_createAsyncPropData(propName, defaultValue) {
		if (!this.asyncProps[propName]) {
			const propTypes = this.component && this.component.props[PROP_TYPES_SYMBOL];
			this.asyncProps[propName] = {
				type: propTypes && propTypes[propName],
				lastValue: null,
				resolvedValue: defaultValue,
				pendingLoadCount: 0,
				resolvedLoadCount: 0
			};
		}
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/layer-state.js
var LayerState = class extends ComponentState {
	constructor({ attributeManager, layer }) {
		super(layer);
		this.attributeManager = attributeManager;
		this.needsRedraw = true;
		this.needsUpdate = true;
		this.subLayers = null;
		this.usesPickingColorCache = false;
	}
	get layer() {
		return this.component;
	}
	_fetch(propName, url) {
		const layer = this.layer;
		const fetch = layer?.props.fetch;
		if (fetch) return fetch(url, {
			propName,
			layer
		});
		return super._fetch(propName, url);
	}
	_onResolve(propName, value) {
		const layer = this.layer;
		if (layer) {
			const onDataLoad = layer.props.onDataLoad;
			if (propName === "data" && onDataLoad) onDataLoad(value, {
				propName,
				layer
			});
		}
	}
	_onError(propName, error) {
		const layer = this.layer;
		if (layer) layer.raiseError(error, `loading ${propName} of ${this.layer}`);
	}
};
//#endregion
//#region node_modules/@deck.gl/core/dist/lib/layer.js
var TRACE_CHANGE_FLAG = "layer.changeFlag";
var TRACE_INITIALIZE = "layer.initialize";
var TRACE_UPDATE = "layer.update";
var TRACE_FINALIZE = "layer.finalize";
var TRACE_MATCHED = "layer.matched";
var MAX_PICKING_COLOR_CACHE_SIZE = 2 ** 24 - 1;
var EMPTY_ARRAY = Object.freeze([]);
var areViewportsEqual = memoize(({ oldViewport, viewport }) => {
	return oldViewport.equals(viewport);
});
var pickingColorCache = new Uint8ClampedArray(0);
var defaultProps$2 = {
	data: {
		type: "data",
		value: EMPTY_ARRAY,
		async: true
	},
	dataComparator: {
		type: "function",
		value: null,
		optional: true
	},
	_dataDiff: {
		type: "function",
		value: (data) => data && data.__diff,
		optional: true
	},
	dataTransform: {
		type: "function",
		value: null,
		optional: true
	},
	onDataLoad: {
		type: "function",
		value: null,
		optional: true
	},
	onError: {
		type: "function",
		value: null,
		optional: true
	},
	fetch: {
		type: "function",
		value: (url, { propName, layer, loaders, loadOptions, signal }) => {
			const { resourceManager } = layer.context;
			loadOptions = loadOptions || layer.getLoadOptions();
			loaders = loaders || layer.props.loaders;
			if (signal) loadOptions = {
				...loadOptions,
				core: {
					...loadOptions?.core,
					fetch: {
						...loadOptions?.core?.fetch,
						signal
					}
				}
			};
			let inResourceManager = resourceManager.contains(url);
			if (!inResourceManager && !loadOptions) {
				resourceManager.add({
					resourceId: url,
					data: load(url, loaders),
					persistent: false
				});
				inResourceManager = true;
			}
			if (inResourceManager) return resourceManager.subscribe({
				resourceId: url,
				onChange: (data) => layer.internalState?.reloadAsyncProp(propName, data),
				consumerId: layer.id,
				requestId: propName
			});
			return load(url, loaders, loadOptions);
		}
	},
	updateTriggers: {},
	visible: true,
	pickable: false,
	opacity: {
		type: "number",
		min: 0,
		max: 1,
		value: 1
	},
	operation: "draw",
	onHover: {
		type: "function",
		value: null,
		optional: true
	},
	onClick: {
		type: "function",
		value: null,
		optional: true
	},
	onDragStart: {
		type: "function",
		value: null,
		optional: true
	},
	onDrag: {
		type: "function",
		value: null,
		optional: true
	},
	onDragEnd: {
		type: "function",
		value: null,
		optional: true
	},
	coordinateSystem: "default",
	coordinateOrigin: {
		type: "array",
		value: [
			0,
			0,
			0
		],
		compare: true
	},
	modelMatrix: {
		type: "array",
		value: null,
		compare: true,
		optional: true
	},
	wrapLongitude: false,
	positionFormat: "XYZ",
	colorFormat: "RGBA",
	parameters: {
		type: "object",
		value: {},
		optional: true,
		compare: 2
	},
	loadOptions: {
		type: "object",
		value: null,
		optional: true,
		ignore: true
	},
	transitions: null,
	extensions: [],
	loaders: {
		type: "array",
		value: [],
		optional: true,
		ignore: true
	},
	getPolygonOffset: {
		type: "function",
		value: ({ layerIndex }) => [0, -layerIndex * 100]
	},
	highlightedObjectIndex: null,
	autoHighlight: false,
	highlightColor: {
		type: "accessor",
		value: [
			0,
			0,
			128,
			128
		]
	}
};
var Layer = class extends Component {
	constructor() {
		super(...arguments);
		this.internalState = null;
		this.lifecycle = LIFECYCLE.NO_STATE;
		this.parent = null;
	}
	static get componentName() {
		return Object.prototype.hasOwnProperty.call(this, "layerName") ? this.layerName : "";
	}
	get root() {
		let layer = this;
		while (layer.parent) layer = layer.parent;
		return layer;
	}
	toString() {
		return `${this.constructor.layerName || this.constructor.name}({id: '${this.props.id}'})`;
	}
	/** Projects a point with current view state from the current layer's coordinate system to screen */
	project(xyz) {
		assert(this.internalState);
		const viewport = this.internalState.viewport || this.context.viewport;
		const [x, y, z] = worldToPixels(getWorldPosition(xyz, {
			viewport,
			modelMatrix: this.props.modelMatrix,
			coordinateOrigin: this.props.coordinateOrigin,
			coordinateSystem: this.props.coordinateSystem
		}), viewport.pixelProjectionMatrix);
		return xyz.length === 2 ? [x, y] : [
			x,
			y,
			z
		];
	}
	/** Unprojects a screen pixel to the current view's default coordinate system
	Note: this does not reverse `project`. */
	unproject(xy) {
		assert(this.internalState);
		return (this.internalState.viewport || this.context.viewport).unproject(xy);
	}
	/** Projects a point with current view state from the current layer's coordinate system to the world space */
	projectPosition(xyz, params) {
		assert(this.internalState);
		return projectPosition(xyz, {
			viewport: this.internalState.viewport || this.context.viewport,
			modelMatrix: this.props.modelMatrix,
			coordinateOrigin: this.props.coordinateOrigin,
			coordinateSystem: this.props.coordinateSystem,
			...params
		});
	}
	/** `true` if this layer renders other layers */
	get isComposite() {
		return false;
	}
	/** `true` if the layer renders to screen */
	get isDrawable() {
		return true;
	}
	/** Updates selected state members and marks the layer for redraw */
	setState(partialState) {
		this.setChangeFlags({ stateChanged: true });
		Object.assign(this.state, partialState);
		this.setNeedsRedraw();
	}
	/** Sets the redraw flag for this layer, will trigger a redraw next animation frame */
	setNeedsRedraw() {
		if (this.internalState) this.internalState.needsRedraw = true;
	}
	/** Mark this layer as needs a deep update */
	setNeedsUpdate() {
		if (this.internalState) {
			this.context.layerManager.setNeedsUpdate(String(this));
			this.internalState.needsUpdate = true;
		}
	}
	/** Returns true if all async resources are loaded */
	get isLoaded() {
		return this.internalState ? !this.internalState.isAsyncPropLoading() : false;
	}
	/** Returns true if using shader-based WGS84 longitude wrapping */
	get wrapLongitude() {
		return this.props.wrapLongitude;
	}
	/** @deprecated Returns true if the layer is visible in the picking pass */
	isPickable() {
		return this.props.pickable && this.props.visible;
	}
	/** Returns an array of models used by this layer, can be overriden by layer subclass */
	getModels() {
		const state = this.state;
		return state && (state.models || state.model && [state.model]) || [];
	}
	/** Update shader input parameters */
	setShaderModuleProps(...props) {
		for (const model of this.getModels()) model.shaderInputs.setProps(...props);
	}
	/** Returns the attribute manager of this layer */
	getAttributeManager() {
		return this.internalState && this.internalState.attributeManager;
	}
	/** Returns the most recent layer that matched to this state
	(When reacting to an async event, this layer may no longer be the latest) */
	getCurrentLayer() {
		return this.internalState && this.internalState.layer;
	}
	/** Returns the default parse options for async props */
	getLoadOptions() {
		return this.props.loadOptions;
	}
	use64bitPositions() {
		const { coordinateSystem } = this.props;
		return coordinateSystem === "default" || coordinateSystem === "lnglat" || coordinateSystem === "cartesian";
	}
	onHover(info, pickingEvent) {
		if (this.props.onHover) return this.props.onHover(info, pickingEvent) || false;
		return false;
	}
	onClick(info, pickingEvent) {
		if (this.props.onClick) return this.props.onClick(info, pickingEvent) || false;
		return false;
	}
	nullPickingColor() {
		return [
			0,
			0,
			0
		];
	}
	encodePickingColor(i, target = []) {
		target[0] = i + 1 & 255;
		target[1] = i + 1 >> 8 & 255;
		target[2] = i + 1 >> 8 >> 8 & 255;
		return target;
	}
	decodePickingColor(color) {
		assert(color instanceof Uint8Array);
		const [i1, i2, i3] = color;
		return i1 + i2 * 256 + i3 * 65536 - 1;
	}
	/** Deduces number of instances. Intention is to support:
	- Explicit setting of numInstances
	- Auto-deduction for ES6 containers that define a size member
	- Auto-deduction for Classic Arrays via the built-in length attribute
	- Auto-deduction via arrays */
	getNumInstances() {
		if (Number.isFinite(this.props.numInstances)) return this.props.numInstances;
		if (this.state && this.state.numInstances !== void 0) return this.state.numInstances;
		return count(this.props.data);
	}
	/** Buffer layout describes how many attribute values are packed for each data object
	The default (null) is one value each object.
	Some data formats (e.g. paths, polygons) have various length. Their buffer layout
	is in the form of [L0, L1, L2, ...] */
	getStartIndices() {
		if (this.props.startIndices) return this.props.startIndices;
		if (this.state && this.state.startIndices) return this.state.startIndices;
		return null;
	}
	getBounds() {
		return this.getAttributeManager()?.getBounds(["positions", "instancePositions"]);
	}
	getShaders(shaders) {
		shaders = mergeShaders(shaders, {
			disableWarnings: true,
			modules: this.context.defaultShaderModules
		});
		for (const extension of this.props.extensions) shaders = mergeShaders(shaders, extension.getShaders.call(this, extension));
		return shaders;
	}
	/** Controls if updateState should be called. By default returns true if any prop has changed */
	shouldUpdateState(params) {
		return params.changeFlags.propsOrDataChanged;
	}
	/** Default implementation, all attributes will be invalidated and updated when data changes */
	updateState(params) {
		const attributeManager = this.getAttributeManager();
		const { dataChanged } = params.changeFlags;
		if (dataChanged && attributeManager) if (Array.isArray(dataChanged)) for (const dataRange of dataChanged) attributeManager.invalidateAll(dataRange);
		else attributeManager.invalidateAll();
		if (attributeManager) {
			const { props } = params;
			const hasPickingBuffer = this.internalState.hasPickingBuffer;
			const needsPickingBuffer = Number.isInteger(props.highlightedObjectIndex) || Boolean(props.pickable) || props.extensions.some((extension) => extension.getNeedsPickingBuffer.call(this, extension));
			if (hasPickingBuffer !== needsPickingBuffer) {
				this.internalState.hasPickingBuffer = needsPickingBuffer;
				const { pickingColors, instancePickingColors } = attributeManager.attributes;
				const pickingColorsAttribute = pickingColors || instancePickingColors;
				if (pickingColorsAttribute) {
					if (needsPickingBuffer && pickingColorsAttribute.constant) {
						pickingColorsAttribute.constant = false;
						attributeManager.invalidate(pickingColorsAttribute.id);
					}
					if (!pickingColorsAttribute.value && !needsPickingBuffer) {
						pickingColorsAttribute.constant = true;
						pickingColorsAttribute.value = [
							0,
							0,
							0
						];
					}
				}
			}
		}
	}
	/** Called once when layer is no longer matched and state will be discarded. Layers can destroy WebGL resources here. */
	finalizeState(context) {
		for (const model of this.getModels()) model.destroy();
		const attributeManager = this.getAttributeManager();
		if (attributeManager) attributeManager.finalize();
		if (this.context) this.context.resourceManager.unsubscribe({ consumerId: this.id });
		if (this.internalState) {
			this.internalState.uniformTransitions.clear();
			this.internalState.finalize();
		}
	}
	draw(opts) {
		for (const model of this.getModels()) model.draw(opts.renderPass);
	}
	getPickingInfo({ info, mode, sourceLayer }) {
		const { index } = info;
		if (index >= 0) {
			if (Array.isArray(this.props.data)) info.object = this.props.data[index];
		}
		return info;
	}
	/** (Internal) Propagate an error event through the system */
	raiseError(error, message) {
		if (message) error = new Error(`${message}: ${error.message}`, { cause: error });
		if (!this.props.onError?.(error)) this.context?.onError?.(error, this);
	}
	/** (Internal) Checks if this layer needs redraw */
	getNeedsRedraw(opts = { clearRedrawFlags: false }) {
		return this._getNeedsRedraw(opts);
	}
	/** (Internal) Checks if this layer needs a deep update */
	needsUpdate() {
		if (!this.internalState) return false;
		return this.internalState.needsUpdate || this.hasUniformTransition() || this.shouldUpdateState(this._getUpdateParams());
	}
	/** Checks if this layer has ongoing uniform transition */
	hasUniformTransition() {
		return this.internalState?.uniformTransitions.active || false;
	}
	/** Called when this layer is rendered into the given viewport */
	activateViewport(viewport) {
		if (!this.internalState) return;
		const oldViewport = this.internalState.viewport;
		this.internalState.viewport = viewport;
		if (!oldViewport || !areViewportsEqual({
			oldViewport,
			viewport
		})) {
			this.setChangeFlags({ viewportChanged: true });
			if (this.isComposite) {
				if (this.needsUpdate()) this.setNeedsUpdate();
			} else this._update();
		}
	}
	/** Default implementation of attribute invalidation, can be redefined */
	invalidateAttribute(name = "all") {
		const attributeManager = this.getAttributeManager();
		if (!attributeManager) return;
		if (name === "all") attributeManager.invalidateAll();
		else attributeManager.invalidate(name);
	}
	/** Send updated attributes to the WebGL model */
	updateAttributes(changedAttributes) {
		let bufferLayoutChanged = false;
		for (const id in changedAttributes) if (changedAttributes[id].layoutChanged()) bufferLayoutChanged = true;
		for (const model of this.getModels()) this._setModelAttributes(model, changedAttributes, bufferLayoutChanged);
	}
	/** Recalculate any attributes if needed */
	_updateAttributes() {
		const attributeManager = this.getAttributeManager();
		if (!attributeManager) return;
		const props = this.props;
		const numInstances = this.getNumInstances();
		const startIndices = this.getStartIndices();
		attributeManager.update({
			data: props.data,
			numInstances,
			startIndices,
			props,
			transitions: props.transitions,
			buffers: props.data.attributes,
			context: this
		});
		const changedAttributes = attributeManager.getChangedAttributes({ clearChangedFlags: true });
		this.updateAttributes(changedAttributes);
	}
	/** Update attribute transitions. This is called in drawLayer, no model updates required. */
	_updateAttributeTransition() {
		const attributeManager = this.getAttributeManager();
		if (attributeManager) attributeManager.updateTransition();
	}
	/** Update uniform (prop) transitions. This is called in updateState, may result in model updates. */
	_updateUniformTransition() {
		const { uniformTransitions } = this.internalState;
		if (uniformTransitions.active) {
			const propsInTransition = uniformTransitions.update();
			const props = Object.create(this.props);
			for (const key in propsInTransition) Object.defineProperty(props, key, { value: propsInTransition[key] });
			return props;
		}
		return this.props;
	}
	/** Updater for the automatically populated instancePickingColors attribute */
	calculateInstancePickingColors(attribute, { numInstances }) {
		if (attribute.constant) return;
		const cacheSize = Math.floor(pickingColorCache.length / 4);
		this.internalState.usesPickingColorCache = true;
		const isPickingColorCacheInvalid = numInstances > 0 && pickingColorCache[0] === 0;
		if (cacheSize < numInstances || isPickingColorCacheInvalid) {
			if (numInstances > MAX_PICKING_COLOR_CACHE_SIZE) defaultLogger.warn("Layer has too many data objects. Picking might not be able to distinguish all objects.")();
			pickingColorCache = typed_array_manager_default.allocate(pickingColorCache, numInstances, {
				size: 4,
				copy: true,
				maxCount: Math.max(numInstances, MAX_PICKING_COLOR_CACHE_SIZE)
			});
			const newCacheSize = Math.floor(pickingColorCache.length / 4);
			const pickingColor = [
				0,
				0,
				0
			];
			const startIndex = isPickingColorCacheInvalid ? 0 : cacheSize;
			for (let i = startIndex; i < newCacheSize; i++) {
				this.encodePickingColor(i, pickingColor);
				pickingColorCache[i * 4 + 0] = pickingColor[0];
				pickingColorCache[i * 4 + 1] = pickingColor[1];
				pickingColorCache[i * 4 + 2] = pickingColor[2];
				pickingColorCache[i * 4 + 3] = 0;
			}
		}
		attribute.value = pickingColorCache.subarray(0, numInstances * 4);
	}
	/** Apply changed attributes to model */
	_setModelAttributes(model, changedAttributes, bufferLayoutChanged = false) {
		if (!Object.keys(changedAttributes).length) return;
		if (bufferLayoutChanged) {
			const attributeManager = this.getAttributeManager();
			model.setBufferLayout(attributeManager.getBufferLayouts(model));
			changedAttributes = attributeManager.getAttributes();
		}
		const excludeAttributes = model.userData?.excludeAttributes || {};
		const attributeBuffers = {};
		const constantAttributes = {};
		for (const name in changedAttributes) {
			if (excludeAttributes[name]) continue;
			const values = changedAttributes[name].getValue();
			for (const attributeName in values) {
				const value = values[attributeName];
				if (value instanceof Buffer) if (changedAttributes[name].settings.isIndexed) model.setIndexBuffer(value);
				else attributeBuffers[attributeName] = value;
				else if (value) constantAttributes[attributeName] = value;
			}
		}
		model.setAttributes(attributeBuffers);
		model.setConstantAttributes(constantAttributes);
	}
	/** (Internal) Sets the picking color at the specified index to null picking color. Used for multi-depth picking.
	This method may be overriden by layer implementations */
	disablePickingIndex(objectIndex) {
		const data = this.props.data;
		if (!("attributes" in data)) {
			this._disablePickingIndex(objectIndex);
			return;
		}
		const { pickingColors, instancePickingColors } = this.getAttributeManager().attributes;
		const colors = pickingColors || instancePickingColors;
		const externalColorAttribute = colors && data.attributes && data.attributes[colors.id];
		if (externalColorAttribute && externalColorAttribute.value) {
			const values = externalColorAttribute.value;
			const objectColor = this.encodePickingColor(objectIndex);
			for (let index = 0; index < data.length; index++) {
				const i = colors.getVertexOffset(index);
				if (values[i] === objectColor[0] && values[i + 1] === objectColor[1] && values[i + 2] === objectColor[2]) this._disablePickingIndex(index);
			}
		} else this._disablePickingIndex(objectIndex);
	}
	_disablePickingIndex(objectIndex) {
		const { pickingColors, instancePickingColors } = this.getAttributeManager().attributes;
		const colors = pickingColors || instancePickingColors;
		if (!colors) return;
		const start = colors.getVertexOffset(objectIndex);
		const end = colors.getVertexOffset(objectIndex + 1);
		colors.buffer.write(new Uint8Array(end - start), start);
	}
	/** (Internal) Re-enable all picking indices after multi-depth picking */
	restorePickingColors() {
		const { pickingColors, instancePickingColors } = this.getAttributeManager().attributes;
		const colors = pickingColors || instancePickingColors;
		if (!colors) return;
		if (this.internalState.usesPickingColorCache && colors.value.buffer !== pickingColorCache.buffer) colors.value = pickingColorCache.subarray(0, colors.value.length);
		colors.updateSubBuffer({ startOffset: 0 });
	}
	_initialize() {
		assert(!this.internalState);
		debug(TRACE_INITIALIZE, this);
		const attributeManager = this._getAttributeManager();
		if (attributeManager) attributeManager.addInstanced({ instancePickingColors: {
			type: "uint8",
			size: 4,
			noAlloc: true,
			update: this.calculateInstancePickingColors
		} });
		this.internalState = new LayerState({
			attributeManager,
			layer: this
		});
		this._clearChangeFlags();
		this.state = {};
		Object.defineProperty(this.state, "attributeManager", { get: () => {
			defaultLogger.deprecated("layer.state.attributeManager", "layer.getAttributeManager()")();
			return attributeManager;
		} });
		this.internalState.uniformTransitions = new UniformTransitionManager(this.context.timeline);
		this.internalState.onAsyncPropUpdated = this._onAsyncPropUpdated.bind(this);
		this.internalState.setAsyncProps(this.props);
		this.initializeState(this.context);
		for (const extension of this.props.extensions) extension.initializeState.call(this, this.context, extension);
		this.setChangeFlags({
			dataChanged: "init",
			propsChanged: "init",
			viewportChanged: true,
			extensionsChanged: true
		});
		this._update();
	}
	/** (Internal) Called by layer manager to transfer state from an old layer */
	_transferState(oldLayer) {
		debug(TRACE_MATCHED, this, this === oldLayer);
		const { state, internalState } = oldLayer;
		if (this === oldLayer) return;
		this.internalState = internalState;
		this.state = state;
		this.internalState.setAsyncProps(this.props);
		this._diffProps(this.props, this.internalState.getOldProps());
	}
	/** (Internal) Called by layer manager when a new layer is added or an existing layer is matched with a new instance */
	_update() {
		const stateNeedsUpdate = this.needsUpdate();
		debug(TRACE_UPDATE, this, stateNeedsUpdate);
		if (!stateNeedsUpdate) return;
		this.context.stats.get("Layer updates").incrementCount();
		const currentProps = this.props;
		const context = this.context;
		const internalState = this.internalState;
		const currentViewport = context.viewport;
		const propsInTransition = this._updateUniformTransition();
		internalState.propsInTransition = propsInTransition;
		context.viewport = internalState.viewport || currentViewport;
		this.props = propsInTransition;
		try {
			const updateParams = this._getUpdateParams();
			const oldModels = this.getModels();
			if (context.device) this.updateState(updateParams);
			else try {
				this.updateState(updateParams);
			} catch (error) {}
			for (const extension of this.props.extensions) extension.updateState.call(this, updateParams, extension);
			this.setNeedsRedraw();
			this._updateAttributes();
			const modelChanged = this.getModels()[0] !== oldModels[0];
			this._postUpdate(updateParams, modelChanged);
		} finally {
			context.viewport = currentViewport;
			this.props = currentProps;
			this._clearChangeFlags();
			internalState.needsUpdate = false;
			internalState.resetOldProps();
		}
	}
	/** (Internal) Called by manager when layer is about to be disposed
	Note: not guaranteed to be called on application shutdown */
	_finalize() {
		debug(TRACE_FINALIZE, this);
		this.finalizeState(this.context);
		for (const extension of this.props.extensions) extension.finalizeState.call(this, this.context, extension);
	}
	_drawLayer({ renderPass, shaderModuleProps = null, uniforms = {}, parameters = {} }) {
		this._updateAttributeTransition();
		const currentProps = this.props;
		const context = this.context;
		this.props = this.internalState.propsInTransition || currentProps;
		try {
			if (shaderModuleProps) this.setShaderModuleProps(shaderModuleProps);
			const { getPolygonOffset } = this.props;
			const offsets = getPolygonOffset && getPolygonOffset(uniforms) || [0, 0];
			if (context.device instanceof WebGLDevice) context.device.setParametersWebGL({ polygonOffset: offsets });
			const webGPUDrawParameters = context.device instanceof WebGLDevice ? null : splitWebGPUDrawParameters(parameters);
			applyModelParameters(this.getModels(), renderPass, parameters, webGPUDrawParameters);
			if (context.device instanceof WebGLDevice) context.device.withParametersWebGL(parameters, () => {
				const opts = {
					renderPass,
					shaderModuleProps,
					uniforms,
					parameters,
					context
				};
				for (const extension of this.props.extensions) extension.draw.call(this, opts, extension);
				this.draw(opts);
			});
			else {
				if (webGPUDrawParameters?.renderPassParameters) renderPass.setParameters(webGPUDrawParameters.renderPassParameters);
				const opts = {
					renderPass,
					shaderModuleProps,
					uniforms,
					parameters,
					context
				};
				for (const extension of this.props.extensions) extension.draw.call(this, opts, extension);
				this.draw(opts);
			}
		} finally {
			this.props = currentProps;
		}
	}
	/** Returns the current change flags */
	getChangeFlags() {
		return this.internalState?.changeFlags;
	}
	/** Dirty some change flags, will be handled by updateLayer */
	setChangeFlags(flags) {
		if (!this.internalState) return;
		const { changeFlags } = this.internalState;
		for (const key in flags) if (flags[key]) {
			let flagChanged = false;
			switch (key) {
				case "dataChanged":
					const dataChangedReason = flags[key];
					const prevDataChangedReason = changeFlags[key];
					if (dataChangedReason && Array.isArray(prevDataChangedReason)) {
						changeFlags.dataChanged = Array.isArray(dataChangedReason) ? prevDataChangedReason.concat(dataChangedReason) : dataChangedReason;
						flagChanged = true;
					}
				default: if (!changeFlags[key]) {
					changeFlags[key] = flags[key];
					flagChanged = true;
				}
			}
			if (flagChanged) debug(TRACE_CHANGE_FLAG, this, key, flags);
		}
		const propsOrDataChanged = Boolean(changeFlags.dataChanged || changeFlags.updateTriggersChanged || changeFlags.propsChanged || changeFlags.extensionsChanged);
		changeFlags.propsOrDataChanged = propsOrDataChanged;
		changeFlags.somethingChanged = propsOrDataChanged || changeFlags.viewportChanged || changeFlags.stateChanged;
	}
	/** Clear all changeFlags, typically after an update */
	_clearChangeFlags() {
		this.internalState.changeFlags = {
			dataChanged: false,
			propsChanged: false,
			updateTriggersChanged: false,
			viewportChanged: false,
			stateChanged: false,
			extensionsChanged: false,
			propsOrDataChanged: false,
			somethingChanged: false
		};
	}
	/** Compares the layers props with old props from a matched older layer
	and extracts change flags that describe what has change so that state
	can be update correctly with minimal effort */
	_diffProps(newProps, oldProps) {
		const changeFlags = diffProps(newProps, oldProps);
		if (changeFlags.updateTriggersChanged) {
			for (const key in changeFlags.updateTriggersChanged) if (changeFlags.updateTriggersChanged[key]) this.invalidateAttribute(key);
		}
		if (changeFlags.transitionsChanged) for (const key in changeFlags.transitionsChanged) this.internalState.uniformTransitions.add(key, oldProps[key], newProps[key], newProps.transitions?.[key]);
		return this.setChangeFlags(changeFlags);
	}
	/** (Internal) called by layer manager to perform extra props validation (in development only) */
	validateProps() {
		validateProps(this.props);
	}
	/** (Internal) Called by deck picker when the hovered object changes to update the auto highlight */
	updateAutoHighlight(info) {
		if (this.props.autoHighlight && !Number.isInteger(this.props.highlightedObjectIndex)) this._updateAutoHighlight(info);
	}
	/** Update picking module parameters to highlight the hovered object */
	_updateAutoHighlight(info) {
		const picking = { highlightedObjectColor: info.picked ? info.color : null };
		const { highlightColor } = this.props;
		if (info.picked && typeof highlightColor === "function") picking.highlightColor = highlightColor(info);
		this.setShaderModuleProps({ picking });
		this.setNeedsRedraw();
	}
	/** Create new attribute manager */
	_getAttributeManager() {
		const context = this.context;
		return new AttributeManager(context.device, {
			id: this.props.id,
			stats: context.stats,
			timeline: context.timeline
		});
	}
	/** Called after updateState to perform common tasks */
	_postUpdate(updateParams, forceUpdate) {
		const { props, oldProps } = updateParams;
		const model = this.state.model;
		if (model?.isInstanced) model.setInstanceCount(this.getNumInstances());
		const { autoHighlight, highlightedObjectIndex, highlightColor } = props;
		if (forceUpdate || oldProps.autoHighlight !== autoHighlight || oldProps.highlightedObjectIndex !== highlightedObjectIndex || oldProps.highlightColor !== highlightColor) {
			const picking = {};
			if (Array.isArray(highlightColor)) picking.highlightColor = highlightColor;
			if (forceUpdate || oldProps.autoHighlight !== autoHighlight || highlightedObjectIndex !== oldProps.highlightedObjectIndex) picking.highlightedObjectColor = Number.isFinite(highlightedObjectIndex) && highlightedObjectIndex >= 0 ? this.encodePickingColor(highlightedObjectIndex) : null;
			this.setShaderModuleProps({ picking });
		}
	}
	_getUpdateParams() {
		return {
			props: this.props,
			oldProps: this.internalState.getOldProps(),
			context: this.context,
			changeFlags: this.internalState.changeFlags
		};
	}
	/** Checks state of attributes and model */
	_getNeedsRedraw(opts) {
		if (!this.internalState) return false;
		let redraw = false;
		redraw = redraw || this.internalState.needsRedraw && this.id;
		const attributeManager = this.getAttributeManager();
		const attributeManagerNeedsRedraw = attributeManager ? attributeManager.getNeedsRedraw(opts) : false;
		redraw = redraw || attributeManagerNeedsRedraw;
		if (redraw) for (const extension of this.props.extensions) extension.onNeedsRedraw.call(this, extension);
		this.internalState.needsRedraw = this.internalState.needsRedraw && !opts.clearRedrawFlags;
		return redraw;
	}
	/** Callback when asyn prop is loaded */
	_onAsyncPropUpdated() {
		this._diffProps(this.props, this.internalState.getOldProps());
		this.setNeedsUpdate();
	}
};
Layer.defaultProps = defaultProps$2;
Layer.layerName = "Layer";
function splitWebGPUDrawParameters(parameters) {
	const { blendConstant, ...pipelineParameters } = parameters;
	return blendConstant ? {
		pipelineParameters,
		renderPassParameters: { blendConstant }
	} : { pipelineParameters };
}
function applyModelParameters(models, renderPass, parameters, webGPUDrawParameters) {
	for (const model of models) if (model.device.type === "webgpu") {
		syncModelAttachmentFormats(model, renderPass);
		model.setParameters({
			...model.parameters,
			...webGPUDrawParameters?.pipelineParameters
		});
	} else model.setParameters(parameters);
}
function syncModelAttachmentFormats(model, renderPass) {
	const framebuffer = renderPass.props.framebuffer || (renderPass.framebuffer ?? null);
	if (!framebuffer) return;
	const colorAttachmentFormats = framebuffer.colorAttachments.map((attachment) => attachment?.texture?.format ?? null);
	const depthStencilAttachmentFormat = framebuffer.depthStencilAttachment?.texture?.format;
	const modelWithProps = model;
	if (!equalAttachmentFormats(modelWithProps.props.colorAttachmentFormats, colorAttachmentFormats) || modelWithProps.props.depthStencilAttachmentFormat !== depthStencilAttachmentFormat) {
		modelWithProps.props.colorAttachmentFormats = colorAttachmentFormats;
		modelWithProps.props.depthStencilAttachmentFormat = depthStencilAttachmentFormat;
		modelWithProps._setPipelineNeedsUpdate("attachment formats");
	}
}
function equalAttachmentFormats(left, right) {
	if (left === right) return true;
	if (!left || !right || left.length !== right.length) return false;
	for (let i = 0; i < left.length; i++) if (left[i] !== right[i]) return false;
	return true;
}
//#endregion
//#region node_modules/@deck.gl/layers/dist/line-layer/line-layer-uniforms.js
var uniformBlockGLSL = `\
layout(std140) uniform lineUniforms {
  float widthScale;
  float widthMinPixels;
  float widthMaxPixels;
  float useShortestPath;
  highp int widthUnits;
} line;
`;
var lineUniforms = {
	name: "line",
	source: "",
	vs: uniformBlockGLSL,
	fs: uniformBlockGLSL,
	uniformTypes: {
		widthScale: "f32",
		widthMinPixels: "f32",
		widthMaxPixels: "f32",
		useShortestPath: "f32",
		widthUnits: "i32"
	}
};
//#endregion
//#region node_modules/@deck.gl/layers/dist/line-layer/line-layer.wgsl.js
var shaderWGSL = `\
// ---------- Helper Structures & Functions ----------

// Placeholder filter functions.
fn deckgl_filter_size(offset: vec3<f32>, geometry: Geometry) -> vec3<f32> {
  return offset;
}
fn deckgl_filter_gl_position(p: vec4<f32>, geometry: Geometry) -> vec4<f32> {
  if (picking.isAttribute > 0.5) {
    // For depth picking, write normalized depth into the picking payload.
    // This mirrors the legacy DECKGL_FILTER_GL_POSITION hook on WebGL.
  }
  return p;
}

// Compute an extrusion offset given a line direction (in clipspace),
// an offset direction (-1 or 1), and a width in pixels.
// Assumes a uniform "project" with a viewportSize field is available.
fn getExtrusionOffset(line_clipspace: vec2<f32>, offset_direction: f32, width: f32) -> vec2<f32> {
  // project.viewportSize should be provided as a uniform (not shown here)
  let dir_screenspace = normalize(line_clipspace * project.viewportSize);
  // Rotate by 90°: (x,y) becomes (-y,x)
  let rotated = vec2<f32>(-dir_screenspace.y, dir_screenspace.x);
  return rotated * offset_direction * width / 2.0;
}

// Splits the line between two points at a given x coordinate.
// Interpolates the y and z components.
fn splitLine(a: vec3<f32>, b: vec3<f32>, x: f32) -> vec3<f32> {
  let t: f32 = (x - a.x) / (b.x - a.x);
  return vec3<f32>(x, a.yz + t * (b.yz - a.yz));
}

// ---------- Uniforms & Global Structures ----------

struct LineUniforms {
  widthScale: f32,
  widthMinPixels: f32,
  widthMaxPixels: f32,
  useShortestPath: f32,
  widthUnits: i32,
};

@group(0) @binding(0)
var<uniform> line: LineUniforms;



// ---------- Vertex Output Structure ----------

struct Varyings {
  @builtin(position) gl_Position: vec4<f32>,
  @location(0) vColor: vec4<f32>,
  @location(1) uv: vec2<f32>,
  @location(2) pickingColor: vec3<f32>,
};

// ---------- Vertex Shader Entry Point ----------

@vertex
fn vertexMain(
  @location(0) positions: vec3<f32>,
  @location(1) instanceSourcePositions: vec3<f32>,
  @location(2) instanceTargetPositions: vec3<f32>,
  @location(3) instanceSourcePositions64Low: vec3<f32>,
  @location(4) instanceTargetPositions64Low: vec3<f32>,
  @location(5) instanceColors: vec4<f32>,
  @location(6) instancePickingColors: vec3<f32>,
  @location(7) instanceWidths: f32
) -> Varyings {
  geometry.worldPosition = instanceSourcePositions;
  geometry.worldPositionAlt = instanceTargetPositions;

  var source_world: vec3<f32> = instanceSourcePositions;
  var target_world: vec3<f32> = instanceTargetPositions;
  var source_world_64low: vec3<f32> = instanceSourcePositions64Low;
  var target_world_64low: vec3<f32> = instanceTargetPositions64Low;

  // Apply shortest-path adjustments if needed.
  if (line.useShortestPath > 0.5 || line.useShortestPath < -0.5) {
    source_world.x = (source_world.x + 180.0 % 360.0) - 180.0;
    target_world.x = (target_world.x + 180.0 % 360.0) - 180.0;
    let deltaLng: f32 = target_world.x - source_world.x;

    if (deltaLng * line.useShortestPath > 180.0) {
      source_world.x = source_world.x + 360.0 * line.useShortestPath;
      source_world = splitLine(source_world, target_world, 180.0 * line.useShortestPath);
      source_world_64low = vec3<f32>(0.0, 0.0, 0.0);
    } else if (deltaLng * line.useShortestPath < -180.0) {
      target_world.x = target_world.x + 360.0 * line.useShortestPath;
      target_world = splitLine(source_world, target_world, 180.0 * line.useShortestPath);
      target_world_64low = vec3<f32>(0.0, 0.0, 0.0);
    } else if (line.useShortestPath < 0.0) {
      var abortOut: Varyings;
      abortOut.gl_Position = vec4<f32>(0.0);
      abortOut.vColor = vec4<f32>(0.0);
      abortOut.uv = vec2<f32>(0.0);
      return abortOut;
    }
  }

  // Project Pos and target positions to clip space.
  let sourceResult = project_position_to_clipspace_and_commonspace(source_world, source_world_64low, vec3<f32>(0.0));
  let targetResult = project_position_to_clipspace_and_commonspace(target_world, target_world_64low, vec3<f32>(0.0));
  let sourcePos: vec4<f32> = sourceResult.clipPosition;
  let targetPos: vec4<f32> = targetResult.clipPosition;
  let source_commonspace: vec4<f32> = sourceResult.commonPosition;
  let target_commonspace: vec4<f32> = targetResult.commonPosition;

  // Interpolate along the line segment.
  let segmentIndex: f32 = positions.x;
  let p: vec4<f32> = sourcePos + segmentIndex * (targetPos - sourcePos);
  geometry.position = source_commonspace + segmentIndex * (target_commonspace - source_commonspace);
  let uv: vec2<f32> = positions.xy;
  geometry.uv = uv;
  geometry.pickingColor = instancePickingColors;

  // Determine width in pixels.
  let widthPixels: f32 = clamp(
    project_unit_size_to_pixel(instanceWidths * line.widthScale, line.widthUnits),
    line.widthMinPixels, line.widthMaxPixels
  );

  // Compute extrusion offset.
  let extrusion: vec2<f32> = getExtrusionOffset(targetPos.xy - sourcePos.xy, positions.y, widthPixels);
  let offset: vec3<f32> = vec3<f32>(extrusion, 0.0);

  // Apply deck.gl filter functions.
  let filteredOffset = deckgl_filter_size(offset, geometry);
  let filteredP = deckgl_filter_gl_position(p, geometry);

  let clipOffset: vec2<f32> = project_pixel_size_to_clipspace(filteredOffset.xy);
  let finalPosition: vec4<f32> = filteredP + vec4<f32>(clipOffset, 0.0, 0.0);

  // Compute color.
  var vColor: vec4<f32> = vec4<f32>(instanceColors.rgb, instanceColors.a * layer.opacity);
  // vColor = deckgl_filter_color(vColor, geometry);

  var output: Varyings;
  output.gl_Position = finalPosition;
  output.vColor = vColor;
  output.uv = uv;
  output.pickingColor = instancePickingColors;
  return output;
}

@fragment
fn fragmentMain(
  @location(0) vColor: vec4<f32>,
  @location(1) uv: vec2<f32>,
  @location(2) pickingColor: vec3<f32>
) -> @location(0) vec4<f32> {
  // Create and initialize geometry with the provided uv.
  var geometry: Geometry;
  geometry.uv = uv;

  // Start with the input color.
  var fragColor: vec4<f32> = vColor;

  if (picking.isActive > 0.5) {
    if (!picking_isColorValid(pickingColor)) {
      discard;
    }
    return vec4<f32>(pickingColor, 1.0);
  }

  if (picking.isHighlightActive > 0.5) {
    let highlightedObjectColor = picking_normalizeColor(picking.highlightedObjectColor);
    if (picking_isColorZero(abs(pickingColor - highlightedObjectColor))) {
      let highLightAlpha = picking.highlightColor.a;
      let blendedAlpha = highLightAlpha + fragColor.a * (1.0 - highLightAlpha);
      if (blendedAlpha > 0.0) {
        let highLightRatio = highLightAlpha / blendedAlpha;
        fragColor = vec4<f32>(
          mix(fragColor.rgb, picking.highlightColor.rgb, highLightRatio),
          blendedAlpha
        );
      } else {
        fragColor = vec4<f32>(fragColor.rgb, 0.0);
      }
    }
  }

  // Apply premultiplied alpha as required by transparent canvas
  fragColor = deckgl_premultiplied_alpha(fragColor);

  return fragColor;
}
`;
//#endregion
//#region node_modules/@deck.gl/layers/dist/line-layer/line-layer-vertex.glsl.js
var line_layer_vertex_glsl_default = `\
#version 300 es
#define SHADER_NAME line-layer-vertex-shader
in vec3 positions;
in vec3 instanceSourcePositions;
in vec3 instanceTargetPositions;
in vec3 instanceSourcePositions64Low;
in vec3 instanceTargetPositions64Low;
in vec4 instanceColors;
in vec3 instancePickingColors;
in float instanceWidths;
out vec4 vColor;
out vec2 uv;
vec2 getExtrusionOffset(vec2 line_clipspace, float offset_direction, float width) {
vec2 dir_screenspace = normalize(line_clipspace * project.viewportSize);
dir_screenspace = vec2(-dir_screenspace.y, dir_screenspace.x);
return dir_screenspace * offset_direction * width / 2.0;
}
vec3 splitLine(vec3 a, vec3 b, float x) {
float t = (x - a.x) / (b.x - a.x);
return vec3(x, mix(a.yz, b.yz, t));
}
void main(void) {
geometry.worldPosition = instanceSourcePositions;
geometry.worldPositionAlt = instanceTargetPositions;
vec3 source_world = instanceSourcePositions;
vec3 target_world = instanceTargetPositions;
vec3 source_world_64low = instanceSourcePositions64Low;
vec3 target_world_64low = instanceTargetPositions64Low;
if (line.useShortestPath > 0.5 || line.useShortestPath < -0.5) {
source_world.x = mod(source_world.x + 180., 360.0) - 180.;
target_world.x = mod(target_world.x + 180., 360.0) - 180.;
float deltaLng = target_world.x - source_world.x;
if (deltaLng * line.useShortestPath > 180.) {
source_world.x += 360. * line.useShortestPath;
source_world = splitLine(source_world, target_world, 180. * line.useShortestPath);
source_world_64low = vec3(0.0);
} else if (deltaLng * line.useShortestPath < -180.) {
target_world.x += 360. * line.useShortestPath;
target_world = splitLine(source_world, target_world, 180. * line.useShortestPath);
target_world_64low = vec3(0.0);
} else if (line.useShortestPath < 0.) {
gl_Position = vec4(0.);
return;
}
}
vec4 source_commonspace;
vec4 target_commonspace;
vec4 source = project_position_to_clipspace(source_world, source_world_64low, vec3(0.), source_commonspace);
vec4 target = project_position_to_clipspace(target_world, target_world_64low, vec3(0.), target_commonspace);
float segmentIndex = positions.x;
vec4 p = mix(source, target, segmentIndex);
geometry.position = mix(source_commonspace, target_commonspace, segmentIndex);
uv = positions.xy;
geometry.uv = uv;
geometry.pickingColor = instancePickingColors;
float widthPixels = clamp(
project_size_to_pixel(instanceWidths * line.widthScale, line.widthUnits),
line.widthMinPixels, line.widthMaxPixels
);
vec3 offset = vec3(
getExtrusionOffset(target.xy - source.xy, positions.y, widthPixels),
0.0);
DECKGL_FILTER_SIZE(offset, geometry);
DECKGL_FILTER_GL_POSITION(p, geometry);
gl_Position = p + vec4(project_pixel_size_to_clipspace(offset.xy), 0.0, 0.0);
vColor = vec4(instanceColors.rgb, instanceColors.a * layer.opacity);
DECKGL_FILTER_COLOR(vColor, geometry);
}
`;
//#endregion
//#region node_modules/@deck.gl/layers/dist/line-layer/line-layer-fragment.glsl.js
var line_layer_fragment_glsl_default = `\
#version 300 es
#define SHADER_NAME line-layer-fragment-shader
precision highp float;
in vec4 vColor;
in vec2 uv;
out vec4 fragColor;
void main(void) {
geometry.uv = uv;
fragColor = vColor;
DECKGL_FILTER_COLOR(fragColor, geometry);
}
`;
//#endregion
//#region node_modules/@deck.gl/layers/dist/line-layer/line-layer.js
var defaultProps$1 = {
	getSourcePosition: {
		type: "accessor",
		value: (x) => x.sourcePosition
	},
	getTargetPosition: {
		type: "accessor",
		value: (x) => x.targetPosition
	},
	getColor: {
		type: "accessor",
		value: [
			0,
			0,
			0,
			255
		]
	},
	getWidth: {
		type: "accessor",
		value: 1
	},
	widthUnits: "pixels",
	widthScale: {
		type: "number",
		value: 1,
		min: 0
	},
	widthMinPixels: {
		type: "number",
		value: 0,
		min: 0
	},
	widthMaxPixels: {
		type: "number",
		value: Number.MAX_SAFE_INTEGER,
		min: 0
	}
};
/**
* A layer that renders straight lines joining pairs of source and target coordinates.
*/
var LineLayer = class extends Layer {
	getBounds() {
		return this.getAttributeManager()?.getBounds(["instanceSourcePositions", "instanceTargetPositions"]);
	}
	getShaders() {
		return super.getShaders({
			vs: line_layer_vertex_glsl_default,
			fs: line_layer_fragment_glsl_default,
			source: shaderWGSL,
			modules: [
				project32_default,
				color_default,
				picking_default,
				lineUniforms
			]
		});
	}
	get wrapLongitude() {
		return false;
	}
	initializeState() {
		this.getAttributeManager().addInstanced({
			instanceSourcePositions: {
				size: 3,
				type: "float64",
				fp64: this.use64bitPositions(),
				transition: true,
				accessor: "getSourcePosition"
			},
			instanceTargetPositions: {
				size: 3,
				type: "float64",
				fp64: this.use64bitPositions(),
				transition: true,
				accessor: "getTargetPosition"
			},
			instanceColors: {
				size: this.props.colorFormat.length,
				type: "unorm8",
				transition: true,
				accessor: "getColor",
				defaultValue: [
					0,
					0,
					0,
					255
				]
			},
			instanceWidths: {
				size: 1,
				transition: true,
				accessor: "getWidth",
				defaultValue: 1
			}
		});
	}
	updateState(params) {
		super.updateState(params);
		if (params.changeFlags.extensionsChanged) {
			this.state.model?.destroy();
			this.state.model = this._getModel();
			this.getAttributeManager().invalidateAll();
		}
	}
	draw({ uniforms }) {
		const { widthUnits, widthScale, widthMinPixels, widthMaxPixels, wrapLongitude } = this.props;
		const model = this.state.model;
		const lineProps = {
			widthUnits: UNIT[widthUnits],
			widthScale,
			widthMinPixels,
			widthMaxPixels,
			useShortestPath: wrapLongitude ? 1 : 0
		};
		model.shaderInputs.setProps({ line: lineProps });
		model.draw(this.context.renderPass);
		if (wrapLongitude) {
			model.shaderInputs.setProps({ line: {
				...lineProps,
				useShortestPath: -1
			} });
			model.draw(this.context.renderPass);
		}
	}
	_getModel() {
		const positions = [
			0,
			-1,
			0,
			0,
			1,
			0,
			1,
			-1,
			0,
			1,
			1,
			0
		];
		return new Model(this.context.device, {
			...this.getShaders(),
			id: this.props.id,
			bufferLayout: this.getAttributeManager().getBufferLayouts(),
			geometry: new Geometry({
				topology: "triangle-strip",
				attributes: { positions: {
					size: 3,
					value: new Float32Array(positions)
				} }
			}),
			isInstanced: true
		});
	}
};
LineLayer.layerName = "LineLayer";
LineLayer.defaultProps = defaultProps$1;
//#endregion
//#region node_modules/maplibre-gl-wind/dist/index.js
var shader = `\
#version 300 es
#define SHADER_NAME wind-particle-transform-vertex-shader

precision highp float;

in vec3 sourcePosition;
out vec3 targetPosition;

uniform sampler2D windTexture;

const vec2 DROP_POSITION = vec2(0);

bool isNaN(float value) {
  return !(value <= 0.f || 0.f <= value);
}

float wrapLongitude(float lng) {
  float wrappedLng = mod(lng + 180.f, 360.f) - 180.f;
  return wrappedLng;
}

float wrapLongitude(float lng, float minLng) {
  float wrappedLng = wrapLongitude(lng);
  if(wrappedLng < minLng) {
    wrappedLng += 360.f;
  }
  return wrappedLng;
}

float randFloat(vec2 seed) {
  return fract(sin(dot(seed.xy, vec2(12.9898f, 78.233f))) * 43758.5453f);
}

vec2 randPoint(vec2 seed) {
  return vec2(randFloat(seed + 1.3f), randFloat(seed + 2.1f));
}

vec2 pointToPosition(vec2 point) {
  point.y = smoothstep(0.f, 1.f, point.y);
  vec2 viewportBoundsMin = wind.viewportBounds.xy;
  vec2 viewportBoundsMax = wind.viewportBounds.zw;
  return mix(viewportBoundsMin, viewportBoundsMax, point);
}

bool isPositionInBounds(vec2 position, vec4 bounds) {
  vec2 boundsMin = bounds.xy;
  vec2 boundsMax = bounds.zw;
  float lng = wrapLongitude(position.x, boundsMin.x);
  float lat = position.y;
  return (boundsMin.x <= lng && lng <= boundsMax.x &&
    boundsMin.y <= lat && lat <= boundsMax.y);
}

bool isPositionInViewport(vec2 position) {
  return isPositionInBounds(position, wind.viewportBounds);
}

vec2 getUV(vec2 pos) {
  return vec2(
    (pos.x - wind.bounds[0]) / (wind.bounds[2] - wind.bounds[0]),
    (pos.y - wind.bounds[3]) / (wind.bounds[1] - wind.bounds[3])
  );
}

bool rasterHasValues(vec4 values) {
  if(wind.imageUnscale[0] < wind.imageUnscale[1]) {
    return values.a >= 1.f;
  } else {
    return !isNaN(values.x);
  }
}

vec2 rasterGetValues(vec4 colour) {
  if(wind.imageUnscale[0] < wind.imageUnscale[1]) {
    return mix(vec2(wind.imageUnscale[0]), vec2(wind.imageUnscale[1]), colour.xy);
  } else {
    return colour.xy;
  }
}

vec2 updatedPosition(vec2 position, vec2 speed) {
  float distortion = cos(radians(position.y));
  vec2 offset;
  offset = vec2(speed.x, speed.y * distortion);
  return position + offset;
}

void main() {
  float particleIndex = mod(float(gl_VertexID), wind.numParticles);
  float particleAge = floor(float(gl_VertexID) / wind.numParticles);

  if(particleAge > 0.f) {
    return;
  }

  if(sourcePosition.xy == DROP_POSITION) {
    vec2 particleSeed = vec2(particleIndex * wind.seed / wind.numParticles);
    vec2 point = randPoint(particleSeed);
    vec2 position = pointToPosition(point);
    targetPosition.xy = position;
    targetPosition.x = wrapLongitude(targetPosition.x);
    return;
  }

  if(wind.viewportZoomChangeFactor > 1.f && mod(particleIndex, wind.viewportZoomChangeFactor) >= 1.f) {
    targetPosition.xy = DROP_POSITION;
    return;
  }

  if(abs(mod(particleIndex, wind.maxAge + 2.f) - mod(wind.time, wind.maxAge + 2.f)) < 1.f) {
    targetPosition.xy = DROP_POSITION;
    return;
  }

  if(!isPositionInBounds(sourcePosition.xy, wind.bounds)) {
    targetPosition.xy = sourcePosition.xy;
    return;
  }

  if(!isPositionInViewport(sourcePosition.xy)) {
    targetPosition.xy = DROP_POSITION;
    return;
  }

  vec2 uv = getUV(sourcePosition.xy);
  vec4 windColour = texture(windTexture, uv);

  if(!rasterHasValues(windColour)) {
    targetPosition.xy = DROP_POSITION;
    return;
  }

  vec2 speed = rasterGetValues(windColour) * wind.speedFactor;
  targetPosition.xy = updatedPosition(sourcePosition.xy, speed);
  targetPosition.x = wrapLongitude(targetPosition.x);
}
`;
var FPS = 60;
var DEFAULT_COLOR = [
	255,
	255,
	255,
	255
];
var COLOR_RAMP_WIDTH = 256;
var uniformBlock = `\
uniform windUniforms {
  float numParticles;
  float maxAge;
  float speedFactor;
  float time;
  float seed;
  vec4 viewportBounds;
  float viewportZoomChangeFactor;
  vec2 imageUnscale;
  vec4 bounds;
} wind;
`;
var windUniforms = {
	name: "wind",
	vs: uniformBlock,
	fs: uniformBlock,
	uniformTypes: {
		numParticles: "f32",
		maxAge: "f32",
		speedFactor: "f32",
		time: "f32",
		seed: "f32",
		viewportBounds: "vec4<f32>",
		viewportZoomChangeFactor: "f32",
		imageUnscale: "vec2<f32>",
		bounds: "vec4<f32>"
	}
};
var defaultColorRamp = [
	[0, [
		59,
		130,
		189,
		255
	]],
	[.1, [
		102,
		194,
		165,
		255
	]],
	[.2, [
		171,
		221,
		164,
		255
	]],
	[.3, [
		230,
		245,
		152,
		255
	]],
	[.4, [
		254,
		224,
		139,
		255
	]],
	[.5, [
		253,
		174,
		97,
		255
	]],
	[.6, [
		244,
		109,
		67,
		255
	]],
	[1, [
		213,
		62,
		79,
		255
	]]
];
var defaultProps = {
	...LineLayer.defaultProps,
	image: {
		type: "image",
		value: null,
		async: true
	},
	imageUnscale: {
		type: "array",
		value: [0, 0]
	},
	numParticles: {
		type: "number",
		min: 1,
		max: 1e6,
		value: 8192
	},
	maxAge: {
		type: "number",
		min: 1,
		max: 255,
		value: 50
	},
	speedFactor: {
		type: "number",
		min: 0,
		max: 1e3,
		value: 50
	},
	color: {
		type: "color",
		value: DEFAULT_COLOR
	},
	colorRamp: {
		type: "array",
		value: defaultColorRamp,
		compare: true
	},
	speedRange: {
		type: "array",
		value: [0, 30],
		compare: true
	},
	width: {
		type: "number",
		value: 1.5
	},
	animate: {
		type: "boolean",
		value: true
	},
	bounds: {
		type: "array",
		value: [
			-180,
			-90,
			180,
			90
		],
		compare: true
	},
	wrapLongitude: true
};
function modulo(x, y) {
	return (x % y + y) % y;
}
function wrapLongitude(lng, minLng = void 0) {
	let wrappedLng = modulo(lng + 180, 360) - 180;
	if (typeof minLng === "number" && wrappedLng < minLng) wrappedLng += 360;
	return wrappedLng;
}
function wrapBounds(bounds) {
	const minLng = bounds[2] - bounds[0] < 360 ? wrapLongitude(bounds[0]) : -180;
	const maxLng = bounds[2] - bounds[0] < 360 ? wrapLongitude(bounds[2], minLng) : 180;
	return [
		minLng,
		Math.max(bounds[1], -90),
		maxLng,
		Math.min(bounds[3], 90)
	];
}
function getViewportBounds(viewport) {
	return wrapBounds(viewport.getBounds());
}
function createColorRampData(colorRamp) {
	const data = new Uint8Array(COLOR_RAMP_WIDTH * 4);
	const sortedStops = [...colorRamp].sort((a, b) => a[0] - b[0]);
	for (let i = 0; i < COLOR_RAMP_WIDTH; i++) {
		const t = i / 255;
		let color = sortedStops[0][1];
		for (let j = 0; j < sortedStops.length - 1; j++) {
			const [t0, c0] = sortedStops[j];
			const [t1, c1] = sortedStops[j + 1];
			if (t >= t0 && t <= t1) {
				const localT = (t - t0) / (t1 - t0);
				color = [
					Math.round(c0[0] + (c1[0] - c0[0]) * localT),
					Math.round(c0[1] + (c1[1] - c0[1]) * localT),
					Math.round(c0[2] + (c1[2] - c0[2]) * localT),
					Math.round((c0[3] ?? 255) + ((c1[3] ?? 255) - (c0[3] ?? 255)) * localT)
				];
				break;
			}
		}
		if (t > sortedStops[sortedStops.length - 1][0]) color = sortedStops[sortedStops.length - 1][1];
		data[i * 4] = color[0];
		data[i * 4 + 1] = color[1];
		data[i * 4 + 2] = color[2];
		data[i * 4 + 3] = color[3] ?? 255;
	}
	return data;
}
var WindParticleLayer = class extends LineLayer {
	static layerName = "WindParticleLayer";
	static defaultProps = defaultProps;
	getNumInstances() {
		return this.state?.numInstances || 0;
	}
	getShaders() {
		const oldShaders = super.getShaders();
		const { speedRange, imageUnscale, bounds } = this.props;
		const [minSpeed, maxSpeed] = speedRange || [0, 30];
		return {
			...oldShaders,
			inject: {
				"vs:#decl": `
          uniform sampler2D windTexture;
          uniform sampler2D colorRampTexture;
          out float vDrop;
          out float vSpeed;
          out vec4 vSpeedColor;
          const vec2 DROP_POSITION = vec2(0);

          vec2 getWindUV(vec2 pos) {
            vec4 b = vec4(${bounds[0].toFixed(6)}, ${bounds[1].toFixed(6)}, ${bounds[2].toFixed(6)}, ${bounds[3].toFixed(6)});
            return vec2(
              (pos.x - b[0]) / (b[2] - b[0]),
              (pos.y - b[3]) / (b[1] - b[3])
            );
          }

          vec2 getWindVelocity(vec4 windColor) {
            vec2 unscale = vec2(${imageUnscale[0].toFixed(6)}, ${imageUnscale[1].toFixed(6)});
            if(unscale[0] < unscale[1]) {
              return mix(vec2(unscale[0]), vec2(unscale[1]), windColor.xy);
            } else {
              return windColor.xy;
            }
          }
        `,
				"vs:#main-start": `
          vDrop = float(instanceSourcePositions.xy == DROP_POSITION || instanceTargetPositions.xy == DROP_POSITION);

          vec2 midPos = (instanceSourcePositions.xy + instanceTargetPositions.xy) * 0.5;
          vec2 windUV = getWindUV(midPos);
          vec4 windColor = texture(windTexture, windUV);
          vec2 velocity = getWindVelocity(windColor);
          float speed = length(velocity);

          float minSpd = ${minSpeed.toFixed(6)};
          float maxSpd = ${maxSpeed.toFixed(6)};
          float speedNorm = clamp((speed - minSpd) / (maxSpd - minSpd), 0.0, 1.0);
          vSpeed = speedNorm;
          vSpeedColor = texture(colorRampTexture, vec2(speedNorm, 0.5));
        `,
				"fs:#decl": `
          in float vDrop;
          in float vSpeed;
          in vec4 vSpeedColor;
        `,
				"fs:#main-start": `
          if (vDrop > 0.5) discard;
        `,
				"fs:DECKGL_FILTER_COLOR": `
          color = vSpeedColor;
          color.a *= geometry.uv.x;
        `
			}
		};
	}
	initializeState() {
		super.initializeState();
		this._setupTransformFeedback();
		const attributeManager = this.getAttributeManager();
		attributeManager.remove([
			"instanceSourcePositions",
			"instanceTargetPositions",
			"instanceColors",
			"instanceWidths"
		]);
		attributeManager.addInstanced({
			instanceSourcePositions: {
				size: 3,
				type: "float32",
				noAlloc: true
			},
			instanceTargetPositions: {
				size: 3,
				type: "float32",
				noAlloc: true
			},
			instanceColors: {
				size: 4,
				type: "float32",
				noAlloc: true
			}
		});
	}
	updateState(params) {
		super.updateState(params);
		const { props, oldProps } = params;
		const { numParticles, maxAge, width, image, colorRamp } = props;
		if (!numParticles || !maxAge || !width) {
			this._deleteTransformFeedback();
			return;
		}
		if (image !== oldProps.image || numParticles !== oldProps.numParticles || maxAge !== oldProps.maxAge || width !== oldProps.width || colorRamp !== oldProps.colorRamp) this._setupTransformFeedback();
	}
	finalizeState(context) {
		this._deleteTransformFeedback();
		super.finalizeState(context);
	}
	draw({ uniforms }) {
		const { initialized } = this.state;
		if (!initialized) return;
		const { animate } = this.props;
		const { sourcePositions, targetPositions, sourcePositions64Low, targetPositions64Low, colors, widths, model, texture, colorRampTexture } = this.state;
		model.setAttributes({
			instanceSourcePositions: sourcePositions,
			instanceTargetPositions: targetPositions,
			instanceColors: colors
		});
		model.setConstantAttributes({
			instanceSourcePositions64Low: sourcePositions64Low,
			instanceTargetPositions64Low: targetPositions64Low,
			instanceWidths: widths
		});
		model.setBindings({
			windTexture: texture,
			colorRampTexture
		});
		super.draw({ uniforms });
		if (animate) this.requestStep();
	}
	_setupTransformFeedback() {
		const { initialized } = this.state || {};
		if (initialized) this._deleteTransformFeedback();
		const { image, numParticles, maxAge, width, colorRamp } = this.props;
		if (typeof image === "string" || image === null) return;
		const numInstances = numParticles * maxAge;
		const numAgedInstances = numParticles * (maxAge - 1);
		const sourcePositions = this.context.device.createBuffer(new Float32Array(numInstances * 3));
		const targetPositions = this.context.device.createBuffer(new Float32Array(numInstances * 3));
		const colors = this.context.device.createBuffer(new Float32Array(new Array(numInstances).fill(void 0).map((_, i) => {
			return [
				1,
				1,
				1,
				1 * (1 - Math.floor(i / numParticles) / maxAge)
			];
		}).flat()));
		const colorRampData = createColorRampData(colorRamp || defaultColorRamp);
		const colorRampTexture = this.context.device.createTexture({
			width: COLOR_RAMP_WIDTH,
			height: 1,
			format: "rgba8unorm",
			sampler: {
				minFilter: "linear",
				magFilter: "linear",
				addressModeU: "clamp-to-edge",
				addressModeV: "clamp-to-edge"
			},
			data: colorRampData
		});
		const sourcePositions64Low = new Float32Array([
			0,
			0,
			0
		]);
		const targetPositions64Low = new Float32Array([
			0,
			0,
			0
		]);
		const widths = new Float32Array([width]);
		const transform = new BufferTransform(this.context.device, {
			attributes: { sourcePosition: sourcePositions },
			bufferLayout: [{
				name: "sourcePosition",
				format: "float32x3"
			}],
			feedbackBuffers: { targetPosition: targetPositions },
			vs: shader,
			varyings: ["targetPosition"],
			modules: [windUniforms],
			vertexCount: numParticles
		});
		this.setState({
			initialized: true,
			numInstances,
			numAgedInstances,
			sourcePositions,
			targetPositions,
			sourcePositions64Low,
			targetPositions64Low,
			colors,
			widths,
			transform,
			texture: image,
			colorRampTexture,
			previousViewportZoom: 0,
			previousTime: 0
		});
	}
	_runTransformFeedback() {
		const { initialized } = this.state || {};
		if (!initialized) return;
		const { viewport, timeline } = this.context;
		const { imageUnscale, bounds, numParticles, speedFactor, maxAge } = this.props;
		const { previousTime, previousViewportZoom, transform, sourcePositions, targetPositions, numAgedInstances, texture } = this.state;
		const time = timeline.getTime();
		if (time === previousTime) return;
		const viewportBounds = getViewportBounds(viewport);
		const viewportZoomChangeFactor = 2 ** ((previousViewportZoom - viewport.zoom) * 4);
		const currentSpeedFactor = speedFactor * .01 / Math.pow(2, viewport.zoom);
		const moduleUniforms = {
			windTexture: texture,
			viewportBounds: viewportBounds || [
				0,
				0,
				0,
				0
			],
			viewportZoomChangeFactor: viewportZoomChangeFactor || 0,
			imageUnscale: imageUnscale || [0, 0],
			bounds,
			numParticles,
			maxAge,
			speedFactor: currentSpeedFactor,
			time,
			seed: Math.random()
		};
		transform.model.shaderInputs.setProps({ wind: moduleUniforms });
		transform.run({
			clearColor: false,
			clearDepth: false,
			clearStencil: false,
			depthReadOnly: true,
			stencilReadOnly: true
		});
		const encoder = this.context.device.createCommandEncoder();
		encoder.copyBufferToBuffer({
			sourceBuffer: sourcePositions,
			sourceOffset: 0,
			destinationBuffer: targetPositions,
			destinationOffset: numParticles * 4 * 3,
			size: numAgedInstances * 4 * 3
		});
		encoder.finish();
		encoder.destroy();
		this.state.sourcePositions = targetPositions;
		this.state.targetPositions = sourcePositions;
		transform.model.setAttributes({ sourcePosition: targetPositions });
		transform.transformFeedback.setBuffers({ targetPosition: sourcePositions });
		this.state.previousViewportZoom = viewport.zoom;
		this.state.previousTime = time;
	}
	_resetTransformFeedback() {
		const { initialized } = this.state || {};
		if (!initialized) return;
		const { sourcePositions, targetPositions, numInstances } = this.state;
		sourcePositions.write(new Float32Array(numInstances * 3));
		targetPositions.write(new Float32Array(numInstances * 3));
	}
	_deleteTransformFeedback() {
		const { initialized } = this.state || {};
		if (!initialized) return;
		const { sourcePositions, targetPositions, colors, transform, colorRampTexture } = this.state;
		sourcePositions?.destroy();
		targetPositions?.destroy();
		colors?.destroy();
		transform?.destroy();
		colorRampTexture?.destroy();
		this.setState({
			initialized: false,
			sourcePositions: void 0,
			targetPositions: void 0,
			colors: void 0,
			transform: void 0,
			colorRampTexture: void 0
		});
	}
	requestStep() {
		const { stepRequested } = this.state || {};
		if (stepRequested) return;
		this.state.stepRequested = true;
		setTimeout(() => {
			this.step();
			this.state.stepRequested = false;
		}, 1e3 / FPS);
	}
	step() {
		this._runTransformFeedback();
		this.setNeedsRedraw();
	}
	clear() {
		this._resetTransformFeedback();
		this.setNeedsRedraw();
	}
};
function degToRad(deg) {
	return deg * Math.PI / 180;
}
function windToUV(speed, direction) {
	const rad = degToRad(direction);
	return {
		u: speed * Math.sin(rad),
		v: speed * Math.cos(rad)
	};
}
function idwInterpolate(x, y, points, power) {
	let sumWeightU = 0;
	let sumWeightV = 0;
	let sumWeight = 0;
	for (const point of points) {
		const dx = x - point.x;
		const dy = y - point.y;
		const distSq = dx * dx + dy * dy;
		if (distSq < 1e-4) return {
			u: point.u,
			v: point.v
		};
		const weight = 1 / Math.pow(Math.sqrt(distSq), power);
		sumWeightU += point.u * weight;
		sumWeightV += point.v * weight;
		sumWeight += weight;
	}
	if (sumWeight === 0) return {
		u: 0,
		v: 0
	};
	return {
		u: sumWeightU / sumWeight,
		v: sumWeightV / sumWeight
	};
}
function generateWindTexture(windData, options = {}) {
	const { width = 360, height = 180, bounds = [
		-180,
		-90,
		180,
		90
	], power = 2 } = options;
	const [west, south, east, north] = bounds;
	const uvPoints = windData.map((point) => {
		const { u, v } = windToUV(point.speed, point.direction);
		return {
			x: (point.lon - west) / (east - west) * width,
			y: (north - point.lat) / (north - south) * height,
			u,
			v
		};
	});
	let uMin = Infinity;
	let uMax = -Infinity;
	let vMin = Infinity;
	let vMax = -Infinity;
	const uvGrid = [];
	for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
		const { u, v } = idwInterpolate(x + .5, y + .5, uvPoints, power);
		uvGrid.push({
			u,
			v
		});
		uMin = Math.min(uMin, u);
		uMax = Math.max(uMax, u);
		vMin = Math.min(vMin, v);
		vMax = Math.max(vMax, v);
	}
	const uRange = uMax - uMin || 1;
	const vRange = vMax - vMin || 1;
	const canvas = document.createElement("canvas");
	canvas.width = width;
	canvas.height = height;
	const ctx = canvas.getContext("2d");
	const imageData = ctx.createImageData(width, height);
	for (let i = 0; i < uvGrid.length; i++) {
		const { u, v } = uvGrid[i];
		const normalizedU = (u - uMin) / uRange;
		const normalizedV = (v - vMin) / vRange;
		const idx = i * 4;
		imageData.data[idx] = Math.round(normalizedU * 255);
		imageData.data[idx + 1] = Math.round(normalizedV * 255);
		imageData.data[idx + 2] = 0;
		imageData.data[idx + 3] = 255;
	}
	ctx.putImageData(imageData, 0, 0);
	return {
		canvas,
		imageData,
		uMin,
		uMax,
		vMin,
		vMax,
		bounds
	};
}
function createWindDataFromOpenWeatherMap(weatherResponses) {
	return weatherResponses.filter((r) => r.wind && typeof r.wind.speed === "number").map((r) => ({
		lat: r.coord.lat,
		lon: r.coord.lon,
		speed: r.wind.speed ?? 0,
		direction: r.wind.deg ?? 0
	}));
}
//#endregion
export { WindParticleLayer, createWindDataFromOpenWeatherMap, generateWindTexture, windUniforms };

//# sourceMappingURL=maplibre-gl-wind.js.map