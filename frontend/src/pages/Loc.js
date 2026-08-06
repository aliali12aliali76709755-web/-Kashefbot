import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { MapPin, Check, X, Loader2, ShieldCheck } from "lucide-react";
import { useLang } from "@/i18n";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function Loc() {
  const { token } = useParams();
  const { tr, toggle, lang } = useLang();
  const [state, setState] = useState("loading"); // loading | ask | sending | shared | declined | done | error
  const [name, setName] = useState("");

  useEffect(() => {
    axios.get(`${API}/loc/${token}`)
      .then((r) => {
        setName(r.data.requester_name || "A user");
        setState(r.data.status === "pending" ? "ask" : "done");
      })
      .catch(() => setState("error"));
  }, [token]);

  const share = () => {
    if (!navigator.geolocation) { setState("error"); return; }
    setState("sending");
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          await axios.post(`${API}/loc/${token}/submit`, {
            lat: pos.coords.latitude, lon: pos.coords.longitude, accuracy: pos.coords.accuracy,
          });
          setState("shared");
        } catch { setState("error"); }
      },
      () => setState("ask"),
      { enableHighAccuracy: true, timeout: 15000 }
    );
  };

  const decline = async () => {
    try { await axios.post(`${API}/loc/${token}/decline`); } catch {}
    setState("declined");
  };

  return (
    <div className="grain grid-bg flex min-h-screen items-center justify-center px-5">
      <button onClick={toggle} className="absolute top-4 end-4 border border-white/15 px-3 py-1.5 font-mono text-xs text-zinc-300 hover:text-cyan-400" data-testid="loc-lang">
        {lang === "ar" ? "EN" : "ع"}
      </button>
      <div className="relative z-10 w-full max-w-md border border-white/15 bg-[#0d0d0f] p-8 text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center border border-cyan-400/50 text-cyan-400" style={{ boxShadow: "0 0 22px -6px var(--cyan)" }}>
          <MapPin size={26} />
        </div>

        {state === "loading" && <p className="mt-6 text-zinc-400"><Loader2 className="mx-auto animate-spin" /></p>}

        {state === "ask" && (
          <>
            <h1 className="mt-6 font-display text-2xl font-black">{tr("طلب مشاركة موقع", "Location Request")}</h1>
            <p className="mt-3 text-zinc-400">
              <b className="text-white">{name}</b> {tr("يطلب مشاركة موقعك الحالي. هل توافق؟", "is requesting to share your current location. Do you agree?")}
            </p>
            <div className="mt-4 flex items-center justify-center gap-1.5 font-mono text-xs text-emerald-400">
              <ShieldCheck size={14} /> {tr("لن يُشارك أي شيء إلا بموافقتك", "Nothing is shared without your consent")}
            </div>
            <div className="mt-8 flex gap-3">
              <button onClick={decline} data-testid="loc-decline" className="flex-1 border border-white/20 py-3 font-semibold hover:text-red-400">
                <X size={16} className="inline" /> {tr("رفض", "Decline")}
              </button>
              <button onClick={share} data-testid="loc-share" className="flex-1 bg-cyan py-3 font-semibold text-black transition-transform hover:scale-[1.02]">
                <Check size={16} className="inline" /> {tr("مشاركة موقعي", "Share my location")}
              </button>
            </div>
          </>
        )}

        {state === "sending" && (
          <>
            <Loader2 className="mx-auto mt-6 animate-spin text-cyan" size={34} />
            <p className="mt-4 text-zinc-400">{tr("جارٍ تحديد موقعك…", "Getting your location…")}</p>
          </>
        )}

        {state === "shared" && (
          <>
            <h1 className="mt-6 font-display text-2xl font-black text-emerald-400">{tr("تمت المشاركة ✅", "Shared ✅")}</h1>
            <p className="mt-3 text-zinc-400">{tr("شكراً، تم إرسال موقعك بأمان.", "Thanks, your location was sent securely.")}</p>
          </>
        )}

        {state === "declined" && (
          <>
            <h1 className="mt-6 font-display text-2xl font-black">{tr("تم الرفض", "Declined")}</h1>
            <p className="mt-3 text-zinc-400">{tr("لم تتم مشاركة أي بيانات.", "No data was shared.")}</p>
          </>
        )}

        {state === "done" && <p className="mt-6 text-zinc-400">{tr("هذا الطلب لم يعد نشطاً.", "This request is no longer active.")}</p>}
        {state === "error" && <p className="mt-6 text-red-400">{tr("رابط غير صالح أو تعذّر تحديد الموقع.", "Invalid link or location unavailable.")}</p>}
      </div>
    </div>
  );
}
