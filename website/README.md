# 🌐 Pipeline Autopsy Website & Interactive Docs

Static marketing landing page and technical documentation site for Pipeline Autopsy.

For complete project documentation, see the [Root README](../README.md).

---

## 📄 Site Structure

- **`index.html`**: Marketing landing page featuring:
  - Interactive trace player and DAG console
  - Visual root cause diagnosis comparison
  - Method and architectural principles
  - SDK checkout and instant download panel
- **`docs.html`**: Complete technical guide for the `autopsy-sdk`:
  - Quickstart with decorator and context-manager examples
  - Trace lifecycle and field specifications
  - Safety model ("The Unplug Test")
- **`downloads/`**: Distributable SDK archives and packages.

---

## 💻 Local Preview

You can preview the website using any static HTTP server:

```bash
# Using Python's built-in HTTP server:
python -m http.server 3000

# Open in browser:
# http://localhost:3000/index.html
# http://localhost:3000/docs.html
```
