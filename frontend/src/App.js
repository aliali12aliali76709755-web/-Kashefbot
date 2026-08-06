import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "sonner";
import { LanguageProvider } from "@/i18n";
import Landing from "@/pages/Landing";
import Admin from "@/pages/Admin";
import Loc from "@/pages/Loc";
import { PaymentSuccess, PaymentCancel } from "@/pages/Payment";

function App() {
  return (
    <div className="App grain">
      <LanguageProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/admin" element={<Admin />} />
            <Route path="/loc/:token" element={<Loc />} />
            <Route path="/payment/success" element={<PaymentSuccess />} />
            <Route path="/payment/cancel" element={<PaymentCancel />} />
          </Routes>
        </BrowserRouter>
        <Toaster theme="dark" position="top-center" richColors />
      </LanguageProvider>
    </div>
  );
}

export default App;
