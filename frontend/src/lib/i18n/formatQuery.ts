import type { Locale } from "./i18n";

export function formatSchemeQuestion(schemeName: string, locale: Locale): string {
  const cleanName = schemeName.trim();
  switch (locale) {
    case "gu":
      return `મને ${cleanName} યોજના વિશે માહિતી આપો`;
    case "hi":
      return `मुझे ${cleanName} योजना के बारे में जानकारी दें`;
    case "mr":
      return `मला ${cleanName} योजनेबद्दल माहिती द्या`;
    case "bn":
      return `আমাকে ${cleanName} স্কিম সম্পর্কে তথ্য দিন`;
    case "ta":
      return `எனக்கு ${cleanName} திட்டம் பற்றி தெரிவிக்கவும்`;
    default:
      return `Tell me about ${cleanName} scheme`;
  }
}

export function formatServiceQuestion(serviceName: string, locale: Locale): string {
  const cleanName = serviceName.trim();
  switch (locale) {
    case "gu":
      return `હું ${cleanName} સેવાનો ઉપયોગ કેવી રીતે કરું?`;
    case "hi":
      return `मैं ${cleanName} सेवा का उपयोग कैसे करूं?`;
    case "mr":
      return `मी ${cleanName} सेवेचा वापर कसा करू?`;
    case "bn":
      return `আমি কীভাবে ${cleanName} পরিষেবা ব্যবহার করব?`;
    case "ta":
      return `நான் ${cleanName} சேவையை எவ்வாறு பயன்படுத்துவது?`;
    default:
      return `How do I use the ${cleanName} service?`;
  }
}

export function formatLegalQuestion(title: string, locale: Locale): string {
  const cleanTitle = title.trim();
  switch (locale) {
    case "gu":
      return `મને ${cleanTitle} કાયદા વિશે માહિતી આપો`;
    case "hi":
      return `मुझे ${cleanTitle} कानून के बारे में जानकारी दें`;
    case "mr":
      return `मला ${cleanTitle} कायद्याबद्दल माहिती द्या`;
    case "bn":
      return `আমাকে ${cleanTitle} আইন সম্পর্কে তথ্য দিন`;
    case "ta":
      return `எனக்கு ${cleanTitle} சட்டம் பற்றி தெரிவிக்கவும்`;
    default:
      return `Tell me about ${cleanTitle}`;
  }
}
