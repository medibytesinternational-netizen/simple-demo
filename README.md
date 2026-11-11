# MediBytes ARD — frontend demo

This repository contains the MediBytes ARD demo UI and the Product-main dictation UI. It is frontend-only: the Simple Demo Python backend and its service code have been removed.

The main ARD demo uses bundled synthetic data. Changes stay in the browser preview and are not sent to a server. The added dictation page preserves the Product-main interface, but audio processing needs an API service that is not included here.

## Run locally

Requirements: Node.js 20 or newer.

    cd frontend
    npm install
    npm run dev

Open the main demo at <http://localhost:5173/dashboard> or the Product-main dictation UI at <http://localhost:5173/product.html>.

## Build and deploy

    cd frontend
    npm run build

The build creates both static pages in frontend/dist. Netlify and the Docker image serve those files; /api/* returns an explicit 404 because no backend is shipped.

## Project layout

- frontend/src/ — existing MediBytes ARD interface and synthetic preview data.
- frontend/src/product/ — Product-main React UI and API client code.
- frontend/product.html — separate entry point for the Product-main UI.
- reports/ — before/after UI report and screenshots.

The Product-main evaluation recordings, transcript JSON files, and test fixtures were not copied from the supplied ZIP.
