import { App as PipelineApp } from "../medibytes/App";
import theme from "../medibytes/styles/theme.module.css";

export function PipelinePage() {
  return <div className={theme.pipelineTheme}><PipelineApp /></div>;
}
