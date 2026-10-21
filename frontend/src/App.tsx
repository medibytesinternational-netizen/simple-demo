import { Navigate, Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import { TimelinePage } from "./pages/Timeline";
import { NotesPage } from "./pages/Notes";
import { SafetyPage } from "./pages/Safety";
import { TasksPage } from "./pages/Tasks";
import { DocumentsPage } from "./pages/Documents";
import { DischargePage } from "./pages/Discharge";
import { RevenuePage } from "./pages/Revenue";
import { DashboardPage } from "./pages/Dashboard";

export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Navigate to="/timeline" replace />} />
        <Route path="/timeline" element={<TimelinePage />} />
        <Route path="/notes" element={<NotesPage />} />
        <Route path="/safety" element={<SafetyPage />} />
        <Route path="/tasks" element={<TasksPage />} />
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="/discharge" element={<DischargePage />} />
        <Route path="/revenue" element={<RevenuePage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="*" element={<Navigate to="/timeline" replace />} />
      </Route>
    </Routes>
  );
}
