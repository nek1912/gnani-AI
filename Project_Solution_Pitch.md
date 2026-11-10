# JanSahay

**Government assistance in the language people understand.**

*Powered by Gnani AI's multilingual speech technology*

## The Problem

For millions of people, accessing government information is not simply a matter of finding the right website or document. It is about understanding complex information, navigating unfamiliar portals, and overcoming language barriers.

A farmer who wants to understand crop insurance benefits should not have to search through lengthy PDFs or struggle with unfamiliar terminology. They should be able to ask a question naturally, in their own language, and understand the answer.

## Our Solution: JanSahay 

**JanSahay** is a multilingual, voice-enabled AI assistant that makes government and cooperative information easier to access and understand.

At the heart of its voice experience is **Gnani AI**.

Using **Gnani Prisma v3.0** for speech-to-text and **Gnani Timbre v3.0** for text-to-speech, JanSahay enables people to speak naturally and receive spoken responses in the languages supported by Gnani's speech APIs. This makes voice the interface between people and complex information — reducing dependence on typing, English-language interfaces, and technical knowledge.

## Powered by Gnani AI. Built for Multilingual Access.

Gnani AI plays a central role in our interaction pipeline:

* **Gnani Prisma v3.0:** Converts spoken questions into text.

* **JanSahay Intelligence:** Understands the query, retrieves relevant information, checks supporting evidence, and generates a grounded response.

* **Gnani Timbre v3.0:** Converts the response into natural speech.

Our experience supports **11 languages**: English, Hindi, Gujarati, Marathi, Bengali, Tamil, Telugu, Kannada, Punjabi, Odia, and Malayalam.

> *Note: Gnani's speech APIs support 10 of these languages. For Odia voice interaction, JanSahay uses configured Sarvam/Azure alternatives.*

## More Than Speech Recognition: Answers Backed by Evidence

Voice alone is not enough. People need answers they can trust. JanSahay combines:

* **Hybrid Retrieval-Augmented Generation (RAG)** using semantic and keyword search.

* A **knowledge base** of government and cooperative information.

* **Web-source discovery** through Tavily and SerpApi.

* Relevance, source, and grounding checks.

* **Evidence-based responses** with citations and abstention when reliable information is insufficient.

## What Can People Use It For?

JanSahay helps users explore:

* Government schemes and eligibility information.

* PMFBY crop-insurance guidance.

* PACS and cooperative governance.

* Financial literacy.

* Legal and by-law information.

* A nine-stage grievance intake and status-guidance prototype.

## The Technology Behind the Experience

`Gnani AI` | `React + Vite` | `FastAPI` | `Supabase + pgvector` | `Hybrid RAG` | `Tavily` | `SerpApi` | `Groq` | `Gemini` | `Sarvam/Azure fallback`

## Our Vision

**Technology should adapt to people's languages — people should not have to adapt to technology.**

By combining Gnani AI's speech capabilities with evidence-grounded retrieval and multilingual AI, JanSahay aims to make essential information more accessible, understandable, and usable through natural conversation.

*Disclaimer: JanSahay is an independent assistance prototype, not an official government service. Its grievance feature provides intake and guidance; it does not submit complaints to government departments.*