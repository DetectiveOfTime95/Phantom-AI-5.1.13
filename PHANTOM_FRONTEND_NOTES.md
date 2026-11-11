# Phantom-AI frontend conversion notes

- Rebranded user-facing and package metadata from Phantom AI to Phantom-AI.
- Replaced the main Electron renderer with the provided Phantom cockpit UI.
- Added a standalone browser frontend in `frontend/index.html`.
- Added the provided Phantom ghost logo to frontend and Electron asset paths.
- Removed the provider secrets embedded in the supplied HTML and replaced them with blank configuration values.
- Set the owner account email to a placeholder; configure real account ownership only in a secure backend.
- The desktop build intentionally has no user account, subscription gate, activation code, or license-file requirement. Optional hosted Stripe links are voluntary support links only; they do not gate features.
