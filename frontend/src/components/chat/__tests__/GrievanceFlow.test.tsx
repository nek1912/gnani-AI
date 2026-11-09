import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { LanguageProvider } from "@/lib/i18n/provider";
import type { ChatResponse } from "@/lib/api";

vi.mock("@/lib/speech", async () => {
  const actual = await vi.importActual<typeof import("@/lib/speech")>("@/lib/speech");
  return { ...actual, speakSegments: vi.fn(async () => {}) };
});

// Mock the API modules used by GrievanceFlow
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    answerGrievanceField: vi.fn(async () => ({ status: "ok" })),
    finalizeGrievanceDraft: vi.fn(async () => ({
      status: "ok",
      grievance: {
        reference: "GRV-20260911-TEST0001",
        category: "Municipal",
        sub_category: "Garbage",
        department: "Municipal Corporation",
        jurisdiction: "Local",
        title: "Garbage Collection Delay",
        description: {
          original: "Garbage has not been collected for exactly 9 days near the community hall.",
          normalized: "Garbage has not been collected for exactly 9 days near the community hall.",
          display: "Garbage has not been collected for exactly 9 days near the community hall.",
        },
        location: {
          ward_number: "17",
          locality: "Shaktinagar West Block",
          area: null,
          city: "Bharuch",
          district: "Bharuch",
          state: "Gujarat",
        },
        submission: {
          portal_name: "Bharuch Municipal Corporation",
          portal_url: "https://bharuch.example.gov.in/",
          department: "Municipal Corporation",
          level: "local",
          steps: ["Visit portal", "Fill form", "Submit"],
          required_documents: ["Aadhaar Card"],
          estimated_timeline: "7 days",
          disclaimer: "Prototype reference only.",
        },
      },
      mixed_language: false,
    })),
    clarifyGrievance: vi.fn(async () => ({
      status: "ok",
      stage: "classification",
      draft_summary: null,
      fields_schema: null,
    })),
  };
});

import { GrievanceFlow } from "../GrievanceFlow";

function makeFinalizedResponse(): ChatResponse {
  return {
    answer: "Your grievance draft is complete.",
    language: "gu",
    domain: "grievance",
    intent: "grievance",
    entities: [],
    confidence: 1.0,
    confidence_level: "high",
    citations: [],
    abstained: false,
    mode: "grievance",
    grievance_stage: "fields",
    grievance_finalized: false,
    conversation_id: "test-conv",
    follow_up_question: null,
    grievance: {
      reference: "GRV-20260911-TEST0001",
      category: "Municipal",
      sub_category: "Garbage",
      department: "Municipal Corporation",
      jurisdiction: "Local",
      title: "Garbage Collection Delay",
      description: {
        original: "Garbage has not been collected for exactly 9 days near the community hall.",
        normalized: "Garbage has not been collected for exactly 9 days near the community hall.",
        display: "Garbage has not been collected for exactly 9 days near the community hall.",
      },
      location: {
        ward_number: "17",
        locality: "Shaktinagar West Block",
        area: null,
        city: "Bharuch",
        district: "Bharuch",
        state: "Gujarat",
      },
      submission: {
        portal_name: "Bharuch Municipal Corporation",
        portal_url: "https://bharuch.example.gov.in/",
        department: "Municipal Corporation",
        level: "local",
        steps: ["Visit portal", "Fill form", "Submit"],
        required_documents: ["Aadhaar Card"],
        estimated_timeline: "7 days",
        disclaimer: "Prototype reference only.",
      },
      fields: null,
    },
  };
}

function makePersistedFinalizedResponse(): ChatResponse {
  // This simulates the response as it would be stored in localStorage
  // AFTER the onGrievanceFinalized callback has patched the message.
  return {
    ...makeFinalizedResponse(),
    grievance_stage: "complete",
    grievance_finalized: true,
  };
}

function makeFieldResponse(): ChatResponse {
  return {
    answer: "What is your ward number?",
    language: "gu",
    domain: "grievance",
    intent: "grievance",
    entities: [],
    confidence: 1.0,
    confidence_level: "high",
    citations: [],
    abstained: false,
    mode: "grievance",
    grievance_stage: "fields",
    grievance_finalized: false,
    conversation_id: "test-conv",
    follow_up_question: null,
    grievance: {
      reference: "GRV-20260911-TEST0001",
      category: "Municipal",
      sub_category: "Garbage",
      department: "Municipal Corporation",
      jurisdiction: "Local",
      title: "Garbage Collection Delay",
      description: {
        original: "Garbage has not been collected.",
        normalized: "Garbage has not been collected.",
        display: "Garbage has not been collected.",
      },
      location: {
        ward_number: null,
        locality: null,
        area: null,
        city: null,
        district: null,
        state: "Gujarat",
      },
      submission: null,
      fields: null,
    },
    grievance_draft_summary: {
      category: "Municipal",
      sub_category: "Garbage",
      department: "Municipal Corporation",
      jurisdiction: "Local",
      title: "Garbage Collection Delay",
      description: "Garbage has not been collected.",
    },
    grievance_fields_schema: {
      mandatory_fields: [
        {
          field: "ward_number",
          field_label: "Ward Number",
          question: "What is your ward number?",
          input_type: "int" as const,
          mandatory: true,
          value: null,
        },
      ],
      optional_fields: [],
    },
  };
}

function renderFlow(
  resp: ChatResponse,
  onSendMessage = vi.fn(),
  onGrievanceFinalized?: (r: ChatResponse) => void,
) {
  return render(
    <MemoryRouter>
      <LanguageProvider>
        <GrievanceFlow
          response={resp}
          onSendMessage={onSendMessage}
          onGrievanceFinalized={onGrievanceFinalized}
        />
      </LanguageProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

describe("GrievanceFlow: finalized state detection from response (Bug 1 persistence)", () => {
  it("renders GrievanceCard when response has submission data but grievance_stage is 'fields'", () => {
    const resp = makeFinalizedResponse();
    expect(resp.grievance_stage).toBe("fields");
    expect(resp.grievance?.submission).toBeTruthy();

    renderFlow(resp);

    expect(screen.getByText(/Grievance draft ready/i)).toBeTruthy();
  });

  it("renders GrievanceCard when grievance_finalized flag is true", () => {
    const resp = makeFinalizedResponse();
    resp.grievance_finalized = true;

    renderFlow(resp);

    expect(screen.getByText(/Grievance draft ready/i)).toBeTruthy();
  });

  it("does not render field panel when grievance is finalized", () => {
    const resp = makeFinalizedResponse();

    renderFlow(resp);

    expect(screen.queryByText(/Please provide/i)).toBeNull();
  });

  it("does not render classification panel when grievance is finalized", () => {
    const resp = makeFinalizedResponse();

    renderFlow(resp);

    expect(screen.queryByText(/Yes, the information is correct/i)).toBeNull();
  });

  it("renders persisted finalized response (grievance_stage='complete', finalized=true) correctly", () => {
    // This simulates what happens when the conversation is restored from
    // localStorage AFTER the onGrievanceFinalized callback patched the message.
    const resp = makePersistedFinalizedResponse();

    renderFlow(resp);

    expect(screen.getByText(/Grievance draft ready/i)).toBeTruthy();
    expect(screen.queryByText(/Please provide/i)).toBeNull();
  });

  it("shows field panel directly for fields-stage response (no classification gate)", () => {
    const resp = makeFieldResponse();
    renderFlow(resp);

    expect(screen.getByText(/What is your ward number/i)).toBeTruthy();
    expect(screen.getByText(/Submit draft/i)).toBeTruthy();
  });

  it("field panel submit button renders for non-finalized response", () => {
    const resp = makeFieldResponse();
    renderFlow(resp);

    expect(screen.getByRole("button", { name: /submit draft/i })).toBeDefined();
  });
});
