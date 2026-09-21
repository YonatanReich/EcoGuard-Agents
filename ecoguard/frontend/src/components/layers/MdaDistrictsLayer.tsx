/**
 * MdaDistrictsLayer — the Magen David Adom regions, as a bundled image.
 *
 * MDA's regions are not published as a file anyone can download, and govmap —
 * which has them — serves that layer as rendered WMS tiles only: WFS and
 * GetFeatureInfo both answer 403 on it. So unlike FireDistrictsLayer, there are
 * no polygons here to draw, tint or label. There is a picture.
 *
 * The picture is fetched once by ecoguard/scripts/fetch_mda_districts.py and
 * committed to data/reference, so the map never talks to govmap at run time.
 * Proxying their WMS live was the other option and it is the wrong one:
 * boundaries that change about once a decade should not cost a request per pan,
 * and it would have put a government service in the path of every redraw.
 *
 * What that costs: govmap's own red outlines and Hebrew region names are baked
 * in at about 98 m/px, so the layer cannot be restyled and goes soft when
 * zoomed well past the country view. Re-run the script with a larger WIDTH if
 * that matters more than the half-megabyte.
 */

import { Layer, Source } from 'react-map-gl/mapbox'

import districtsImage from '../../../../data/reference/mda_districts.png'


/**
 * The degree corners the image was rendered for — WEST/SOUTH/EAST/NORTH in
 * fetch_mda_districts.py, and meaningless apart from it.
 *
 * The render is EPSG:3857 and the map is EPSG:3857, so the image lines up by
 * construction: only these four corners position it. Change them here and in
 * the script together, or the regions will sit off the country.
 */
const WEST = 34.15
const SOUTH = 29.40
const EAST = 35.95
const NORTH = 33.45


type MdaDistrictsLayerProps = {
  /** Whether the overlay is visible. */
  visible?: boolean

  /** Opacity of the image above the base map. */
  opacity?: number
}


function MdaDistrictsLayer({
  visible = true,
  opacity = 0.6,
}: MdaDistrictsLayerProps) {
  if (!visible) return null

  return (
    <Source
      id="mda-districts"
      type="image"
      url={districtsImage}
      coordinates={[
        // Mapbox image coordinates run top-left, top-right, bottom-right,
        // bottom-left.
        [WEST, NORTH],
        [EAST, NORTH],
        [EAST, SOUTH],
        [WEST, SOUTH],
      ]}
    >
      <Layer
        id="mda-districts"
        type="raster"
        paint={{
          'raster-opacity': opacity,
          // The image is being scaled up past its native resolution; nearest
          // neighbour would turn the outlines into staircases.
          'raster-resampling': 'linear',
          'raster-fade-duration': 300,
        }}
      />
    </Source>
  )
}


export default MdaDistrictsLayer
