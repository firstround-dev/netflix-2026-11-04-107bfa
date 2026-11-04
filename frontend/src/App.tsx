import { Link, Route, Routes } from "react-router-dom";
import { NameBar } from "./actor";
import { ReviewPage } from "./pages/ReviewPage";
import { SetPage } from "./pages/SetPage";
import { SetsPage } from "./pages/SetsPage";

export function App() {
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">
          Trivia Localisation Desk
        </Link>
        <NameBar />
      </header>
      <main className="container">
        <Routes>
          <Route path="/" element={<SetsPage />} />
          <Route path="/sets/:setId" element={<SetPage />} />
          <Route path="/sets/:setId/review/:locale" element={<ReviewPage />} />
          <Route path="*" element={<p>Page not found.</p>} />
        </Routes>
      </main>
    </>
  );
}
