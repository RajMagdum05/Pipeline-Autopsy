import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Activity, Shield, Layers, Cpu, FileText } from 'lucide-react';

interface LayoutProps {
  children: React.ReactNode;
}

export const Layout: React.FC<LayoutProps> = ({ children }) => {
  const location = useLocation();

  const isClaimsActive = location.pathname.startsWith('/claims') || location.pathname === '/';

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col font-sans">
      {/* Top Header & Navigation */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            {/* Logo & Product Title */}
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-slate-900 text-white flex items-center justify-center font-bold text-lg shadow-xs">
                <Activity className="w-5 h-5 text-emerald-400" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="text-base font-semibold text-slate-900 leading-tight">
                    Pipeline Autopsy
                  </h1>
                  <span className="text-[10px] font-medium tracking-wide uppercase px-2 py-0.5 bg-slate-100 text-slate-600 rounded border border-slate-200">
                    Enterprise
                  </span>
                </div>
                <p className="text-xs text-slate-500">
                  Insurance Claim Processing
                </p>
              </div>
            </div>

            {/* Navigation Tabs */}
            <nav className="flex items-center gap-1 sm:gap-2">
              <Link
                to="/claims"
                className={`inline-flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                  isClaimsActive
                    ? 'bg-slate-100 text-slate-900 border border-slate-200'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
                }`}
              >
                <FileText className="w-4 h-4 text-slate-500" />
                Claims
              </Link>

              {/* Upcoming nav items marked disabled/planned */}
              <span
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-slate-400 cursor-not-allowed opacity-60"
                title="Pipeline view coming soon"
              >
                <Layers className="w-4 h-4 text-slate-400" />
                Pipeline
              </span>

              <span
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-slate-400 cursor-not-allowed opacity-60"
                title="Executions log coming soon"
              >
                <Cpu className="w-4 h-4 text-slate-400" />
                Executions
              </span>

              <span
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-slate-400 cursor-not-allowed opacity-60"
                title="Autopsy RCA engine coming soon"
              >
                <Shield className="w-4 h-4 text-slate-400" />
                Autopsy
              </span>
            </nav>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {children}
      </main>

      {/* Footer */}
      <footer className="bg-white border-t border-slate-200 py-4 mt-auto">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between text-xs text-slate-500 gap-2">
          <div>
            Pipeline Autopsy &bull; Observability Platform
          </div>
          <div className="flex items-center gap-4 text-slate-400">
            <span>Frontend Shell v0.1.0</span>
            <span>&bull;</span>
            <span>Local Mock Mode</span>
          </div>
        </div>
      </footer>
    </div>
  );
};
