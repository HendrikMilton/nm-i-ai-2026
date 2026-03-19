import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/Layout';
import { LogsPage } from './pages/LogsPage';
import { ReplayPage } from './pages/ReplayPage';
import { ThemeContext, useThemeState } from './hooks/useTheme';
import './compiled.css';

export function App() {
    const themeState = useThemeState();

    return (
        <ThemeContext.Provider value={themeState}>
            <BrowserRouter>
                <Layout>
                    <Routes>
                        <Route path="/" element={<Navigate to="/logs" replace />} />
                        <Route path="/logs" element={<LogsPage />} />
                        <Route path="/replay/:challenge/:index" element={<ReplayPage />} />
                    </Routes>
                </Layout>
            </BrowserRouter>
        </ThemeContext.Provider>
    );
}

export default App;
