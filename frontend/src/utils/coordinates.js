import gcoord from 'gcoord'

export const wgs84ToGcj02 = ([lng, lat]) => gcoord.transform(
  [Number(lng), Number(lat)],
  gcoord.WGS84,
  gcoord.GCJ02,
)

export const wgs84CoordinatesToGcj02 = coordinates => coordinates.map(wgs84ToGcj02)

export const gcj02ToWgs84 = ([lng, lat]) => gcoord.transform(
  [Number(lng), Number(lat)],
  gcoord.GCJ02,
  gcoord.WGS84,
)
