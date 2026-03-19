import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/Layout';
import { LogsPage } from './pages/LogsPage';
import { ReplayPage } from './pages/ReplayPage';
import { DatasetPage } from './pages/DatasetPage';
import { ProductsPage } from './pages/ProductsPage';
import { TrainingPage } from './pages/TrainingPage';
import { ThemeContext, useThemeState } from './hooks/useTheme';
import './compiled.css';

export function App() {
    const themeState = useThemeState();

    return (
        <ThemeContext.Provider value={themeState}>
            <BrowserRouter>
                <Layout>
                    <Routes>
                        <Route path="/" element={<Navigate to="/dataset" replace />} />
                        <Route path="/logs" element={<LogsPage />} />
                        <Route path="/replay/:challenge/:index" element={<ReplayPage />} />
                        <Route path="/dataset" element={<DatasetPage />} />
                        <Route path="/products" element={<ProductsPage />} />
                        <Route path="/training" element={<TrainingPage />} />
                    </Routes>
                </Layout>
            </BrowserRouter>
        </ThemeContext.Provider>
    );
}

export default App;
