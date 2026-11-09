import { describe, it, expect, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { ThinkingProcess } from "../ThinkingProcess";
import type { StepEvent } from "@/lib/api";

afterEach(() => cleanup());

const makeSteps = (overrides: Partial<StepEvent>[] = []): StepEvent[] => [
  { id: "retrieval_start", label: "Searching sources", detail: "Querying document store", status: "completed", ...overrides[0] },
  { id: "static_done", label: "Document search complete", detail: "Found 12 chunks", status: "completed", ...overrides[1] },
  { id: "llm_generate", label: "Generating response", detail: "Generating grounded response", status: "active", ...overrides[2] },
];

describe("ThinkingProcess", () => {
  it("renders nothing when steps are empty", () => {
    const { container } = render(<ThinkingProcess steps={[]} isStreaming={false} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders all steps when not streaming", () => {
    render(<ThinkingProcess steps={makeSteps()} isStreaming={false} />);
    expect(screen.getByText("Searching sources")).toBeTruthy();
    expect(screen.getByText("Document search complete")).toBeTruthy();
    expect(screen.getByText("Generating response")).toBeTruthy();
  });

  it("shows spinner for active step", () => {
    render(<ThinkingProcess steps={makeSteps()} isStreaming={false} />);
    const spinners = document.querySelectorAll("svg.animate-spin");
    expect(spinners.length).toBe(1);
  });

  it("auto-collapses to summary when streaming starts", () => {
    render(<ThinkingProcess steps={makeSteps()} isStreaming={true} />);
    expect(screen.getByText("Generating response")).toBeTruthy();
    expect(screen.queryByText("Searching sources")).toBeNull();
  });

  it("expands on dropdown click", () => {
    render(<ThinkingProcess steps={makeSteps()} isStreaming={true} />);
    fireEvent.click(screen.getByText("Generating response"));
    expect(screen.getByText("Searching sources")).toBeTruthy();
  });

  it("shows detail text when expanded", () => {
    render(<ThinkingProcess steps={makeSteps()} isStreaming={false} />);
    expect(screen.getByText("Querying document store")).toBeTruthy();
    expect(screen.getByText("Found 12 chunks")).toBeTruthy();
  });

  it("sorts steps in pipeline order", () => {
    const unsorted: StepEvent[] = [
      { id: "llm_generate", label: "Generating", detail: "", status: "completed" },
      { id: "retrieval_start", label: "Searching", detail: "", status: "completed" },
    ];
    render(<ThinkingProcess steps={unsorted} isStreaming={false} />);
    const items = screen.getAllByText(/(Searching|Generating)/);
    expect(items[0].textContent).toBe("Searching");
    expect(items[1].textContent).toBe("Generating");
  });

  it("remains visible and collapsed when isComplete is true", () => {
    const completedSteps: StepEvent[] = [
      { id: "retrieval_start", label: "Searching sources", detail: "Querying store", status: "completed" },
      { id: "static_done", label: "Document search complete", detail: "10 chunks", status: "completed" },
    ];
    render(<ThinkingProcess steps={completedSteps} isStreaming={false} isComplete={true} initialDurationSec={4} />);
    expect(screen.getByText("Thought for 4 seconds")).toBeTruthy();
    expect(screen.getByText("2 steps complete")).toBeTruthy();
    expect(screen.queryByText("Querying store")).toBeNull();

    // Click to expand completed thoughts
    fireEvent.click(screen.getByText("2 steps complete"));
    expect(screen.getByText("Querying store")).toBeTruthy();
    expect(screen.getByText("10 chunks")).toBeTruthy();
  });
});
