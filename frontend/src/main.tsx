import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";

import App from './App.tsx'
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import jsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker'
import yamlWorker from "./yaml.worker.ts?worker";


self.MonacoEnvironment = {
  getWorker(_, label) {
    if (label === 'yaml') {
      return new yamlWorker()
    }
    if (label === 'json') {
      return new jsonWorker()
    }
    return new editorWorker()
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
      <App />
  </StrictMode>,
)

loader.config({ monaco });
