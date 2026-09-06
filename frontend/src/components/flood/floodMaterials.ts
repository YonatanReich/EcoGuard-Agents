import {
  buildModuleUrl,
  Color,
  Material,
} from 'cesium'

export const FLOOD_WATER_BASE_ALPHA = 0.42
export const FLOOD_WATER_BLEND_ALPHA = 0.25
export const FLOOD_FLOW_ALPHA = 0.5
export const FLOOD_FRONT_ALPHA = 0.62

export function createFloodWaterMaterial() {
  return Material.fromType('Water', {
    baseWaterColor: Color.fromCssColorString('#176b87').withAlpha(FLOOD_WATER_BASE_ALPHA),
    blendColor: Color.fromCssColorString('#7bc4cf').withAlpha(FLOOD_WATER_BLEND_ALPHA),
    normalMap: buildModuleUrl('Assets/Textures/waterNormalsSmall.jpg'),
    specularMap: Material.DefaultImageId,
    frequency: 240,
    animationSpeed: 0.008,
    amplitude: 2.7,
    specularIntensity: 0.58,
    fadeFactor: 1,
  })
}

export function createDirectionalFlowMaterial() {
  return new Material({
    translucent: true,
    fabric: {
      uniforms: {
        color: Color.fromCssColorString('#c5e9e9').withAlpha(FLOOD_FLOW_ALPHA),
        time: 0,
        repeat: 9,
        speed: 0.24,
      },
      source: `
        czm_material czm_getMaterial(czm_materialInput materialInput)
        {
          czm_material material = czm_getDefaultMaterial(materialInput);
          float phase = fract(materialInput.st.s * repeat - time * speed);
          float primary = 1.0 - smoothstep(0.12, 0.46, phase);
          float secondaryPhase = fract(phase + 0.48);
          float secondary = (1.0 - smoothstep(0.08, 0.34, secondaryPhase)) * 0.45;
          float streak = max(primary, secondary);
          float edgeFade = pow(sin(3.14159265 * materialInput.st.t), 1.35);
          float corridorFade = smoothstep(0.0, 0.06, materialInput.st.s) *
            (1.0 - smoothstep(0.94, 1.0, materialInput.st.s));
          material.diffuse = mix(color.rgb * 0.72, color.rgb, streak);
          material.emission = color.rgb * streak * 0.36;
          material.alpha = color.a * edgeFade * corridorFade * (0.16 + streak * 0.84);
          return material;
        }
      `,
    },
  })
}

export function createFloodFrontMaterial() {
  return new Material({
    translucent: true,
    fabric: {
      uniforms: {
        color: Color.fromCssColorString('#e1f4f2').withAlpha(FLOOD_FRONT_ALPHA),
        time: 0,
      },
      source: `
        czm_material czm_getMaterial(czm_materialInput materialInput)
        {
          czm_material material = czm_getDefaultMaterial(materialInput);
          float edgeFade = pow(sin(3.14159265 * materialInput.st.t), 1.7);
          float frontFade = smoothstep(0.0, 0.72, materialInput.st.s);
          float foam = 0.68 + 0.32 * sin(
            materialInput.st.s * 34.0 - time * 2.1 + materialInput.st.t * 7.0
          );
          material.diffuse = color.rgb;
          material.emission = color.rgb * foam * 0.44;
          material.alpha = color.a * edgeFade * frontFade * foam;
          return material;
        }
      `,
    },
  })
}
