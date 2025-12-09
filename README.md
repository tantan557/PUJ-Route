# Isochrone Map Generator (Streamlit)

This Streamlit app allows users to upload CSV/Excel files containing route stops and generates interactive **isochrone maps**.

## Features

- Upload multiple CSV/Excel files (each file = one route)
- Customizable walking speed and time ranges
- Generates isochrone polygons for each stop
- Download interactive HTML map
- Layer control to toggle routes/stops/isochrones

## CSV / Excel format

Each file must contain columns:

- `lat` : latitude
- `lon` : longitude
- `name` : stop name (optional: `stop_number`, `address`)

## Deployment

1. Push this folder to GitHub
2. Go to [Streamlit Cloud](https://share.streamlit.io) → New App → Select repo → Deploy
