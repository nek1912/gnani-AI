import { describe, it, expect, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { LanguageProvider } from "@/lib/i18n/provider";
import type { Grievance } from "@/lib/api";

import { GrievanceCard } from "../GrievanceCard";

afterEach(() => {
  cleanup();
});

function renderCard(grievance: Grievance) {
  return render(
    <MemoryRouter>
      <LanguageProvider>
        <GrievanceCard grievance={grievance} />
      </LanguageProvider>
    </MemoryRouter>,
  );
}

function makeGrievanceWithFields(fields: Record<string, string> | null): Grievance {
  return {
    reference: "GRV-20260912-TEST0001",
    category: "Agriculture",
    sub_category: "PMFBY Claim Delay",
    department: "Agriculture Department / Insurance Company (PMFBY)",
    jurisdiction: "State",
    title: "PMFBY Crop Insurance Claim Delay",
    description: {
      original: "My PMFBY crop insurance claim is delayed",
      normalized: "My PMFBY crop insurance claim is delayed",
      display: "My PMFBY crop insurance claim is delayed",
    },
    fields,
    location: {
      ward_number: null,
      locality: null,
      area: null,
      city: null,
      district: null,
      state: "Gujarat",
    },
    submission: {
      portal_name: "PMFBY Portal",
      portal_url: "https://pmfby.gov.in/",
      department: "Agriculture Department",
      level: "state",
      steps: ["Login to portal", "File complaint"],
      required_documents: ["Aadhaar Card"],
      estimated_timeline: "30 days",
      disclaimer: "Prototype reference only.",
    },
  };
}

describe("GrievanceCard fields rendering", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders structured field values when fields are present", () => {
    const fields = {
      farmer_name: "Rahul Kumar",
      application_id: "ABC123456",
      crop: "Cotton",
      season: "Kharif",
      year: "2026",
      insurance_company: "National Insurance Co.",
      bank_name: "State Bank of India",
    };
    renderCard(makeGrievanceWithFields(fields));

    expect(screen.getByText("Farmer Name")).toBeTruthy();
    expect(screen.getByText("Rahul Kumar")).toBeTruthy();
    expect(screen.getByText("Application ID")).toBeTruthy();
    expect(screen.getByText("ABC123456")).toBeTruthy();
    expect(screen.getByText("Crop")).toBeTruthy();
    expect(screen.getByText("Cotton")).toBeTruthy();
    expect(screen.getByText("Season")).toBeTruthy();
    expect(screen.getByText("Kharif")).toBeTruthy();
    expect(screen.getByText("Year")).toBeTruthy();
    expect(screen.getByText("2026")).toBeTruthy();
    expect(screen.getByText("Insurance Company")).toBeTruthy();
    expect(screen.getByText("National Insurance Co.")).toBeTruthy();
    expect(screen.getByText("Bank Name")).toBeTruthy();
    expect(screen.getByText("State Bank of India")).toBeTruthy();
  });

  it("does not render fields section when fields is null", () => {
    renderCard(makeGrievanceWithFields(null));

    expect(screen.queryByText("Farmer Name")).toBeNull();
    expect(screen.queryByText("Rahul Kumar")).toBeNull();
  });

  it("does not render fields section when fields is empty", () => {
    renderCard(makeGrievanceWithFields({}));

    expect(screen.queryByText("Farmer Name")).toBeNull();
  });

  it("still renders description and location when fields are present", () => {
    const fields = { farmer_name: "Rahul Kumar" };
    renderCard(makeGrievanceWithFields(fields));

    expect(screen.getByText("My PMFBY crop insurance claim is delayed")).toBeTruthy();
    expect(screen.getByText("Gujarat")).toBeTruthy();
    expect(screen.getByText("PMFBY Portal")).toBeTruthy();
  });

  it("renders field labels as title-cased snake_case keys", () => {
    const fields = { application_id: "ABC123" };
    renderCard(makeGrievanceWithFields(fields));

    expect(screen.getByText("Application ID")).toBeTruthy();
  });
});
