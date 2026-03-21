import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/Layout';
import { LogsPage } from './pages/LogsPage';
import { ReplayPage } from './pages/ReplayPage';
import { ChallengePage } from './pages/ChallengePage';
import { DatasetPage } from './pages/DatasetPage';
import { ProductsPage } from './pages/ProductsPage';
import { TrainingPage } from './pages/TrainingPage';
import { AstarPage } from './pages/AstarPage';
import { ThemeContext, useThemeState } from './hooks/useTheme';
import './compiled.css';

export function App() {
    const themeState = useThemeState();

    return (
        <ThemeContext.Provider value={themeState}>
            <BrowserRouter>
                <Layout>
                    <Routes>
                        <Route path="/" element={<Navigate to="/challenges/2" replace />} />
                        <Route path="/challenges/2" element={<ChallengePage />} />
                        <Route path="/challenges/2/dataset" element={<DatasetPage />} />
                        <Route path="/challenges/2/products" element={<ProductsPage />} />
                        <Route path="/challenges/2/training" element={<TrainingPage />} />
                        <Route path="/challenges/3/astar" element={<AstarPage />} />
                        <Route path="/logs" element={<LogsPage />} />
                        <Route path="/replay/:challenge/:index" element={<ReplayPage />} />
                    </Routes>
                </Layout>
            </BrowserRouter>
        </ThemeContext.Provider>
    );
}

export default App;
