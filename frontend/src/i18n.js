import React, { createContext, useContext, useEffect, useState } from "react";

const LangContext = createContext(null);

export function LanguageProvider({ children }) {
  const [lang, setLang] = useState(() => localStorage.getItem("lang") || "ar");

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
    localStorage.setItem("lang", lang);
  }, [lang]);

  const tr = (ar, en) => (lang === "ar" ? ar : en);
  const toggle = () => setLang((l) => (l === "ar" ? "en" : "ar"));
  const dir = lang === "ar" ? "rtl" : "ltr";

  return (
    <LangContext.Provider value={{ lang, setLang, toggle, tr, dir }}>
      {children}
    </LangContext.Provider>
  );
}

export function useLang() {
  return useContext(LangContext);
}
