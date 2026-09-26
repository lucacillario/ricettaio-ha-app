import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const categories = [
  { id: "52736cf1-1c9c-4aee-a4c9-9d23d11b391d", name: "Primi", slug: "primi", color: "#d39a38", sort_order: 1 },
];

const recipePage = {
  items: [
    {
      id: "8ed2a695-c046-49e4-bc31-26a0d4ecebb4",
      title: "Pasta e ceci",
      slug: "pasta-e-ceci",
      description: "Cremosa e semplice",
      category_id: categories[0].id,
      category_name: "Primi",
      difficulty: "easy",
      base_servings: "4",
      serving_unit: "persone",
      total_time_minutes: 35,
      tags: ["dispensa"],
      favorite: true,
      has_cover: false,
      revision: 1,
      updated_at: "2026-09-25T10:00:00Z",
      deleted_at: null,
    },
  ],
  total: 1,
  limit: 50,
  offset: 0,
};

describe("RicettAIo", () => {
  beforeEach(() => {
    window.location.hash = "#/";
    Object.defineProperty(Element.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(() => ({ animation: "home-assistant" })),
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("ai/chat/stream")) {
          const result = JSON.stringify({
            message: "Ciao! Sono RicettAIo.",
            referenced_recipe_ids: [],
            proposal: null,
          });
          return new Response(
            `event: delta\ndata: {"text":"Ciao! "}\n\n`
              + `event: delta\ndata: {"text":"Sono RicettAIo."}\n\n`
              + `event: result\ndata: ${result}\n\n`
              + "event: done\ndata: {}\n\n",
            { status: 200, headers: { "Content-Type": "text/event-stream" } },
          );
        }
        const body = url.includes("categories")
          ? categories
          : recipePage;
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    Reflect.deleteProperty(Element.prototype, "scrollIntoView");
  });

  it("mostra l'archivio e una ricetta", async () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: /cosa cuciniamo oggi/i })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Pasta e ceci")).toBeInTheDocument());
    expect(screen.getByText(/35 min/)).toBeInTheDocument();
    expect(screen.getByText(/dispensa/)).toBeInTheDocument();
  });

  it("non usa il risultato di scrollIntoView come cleanup della chat", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /chiedi all'ai/i }));
    fireEvent.change(screen.getByRole("textbox", { name: "Messaggio" }), {
      target: { value: "Ciao" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Invia" }));

    await waitFor(() => expect(screen.getByText("Ciao! Sono RicettAIo.")).toBeInTheDocument());
  });

  it("mantiene la virgola mentre si inseriscono i tag", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /nuova ricetta/i }));
    await waitFor(() => expect(screen.getByRole("heading", { name: /aggiungi qualcosa di buono/i })).toBeInTheDocument());

    const tags = screen.getByLabelText(/tag \(separati da virgola\)/i);
    fireEvent.change(tags, { target: { value: "veloce," } });
    expect(tags).toHaveValue("veloce,");
    fireEvent.change(tags, { target: { value: "veloce, vegetariano" } });
    expect(tags).toHaveValue("veloce, vegetariano");
  });

  it("mostra i filtri solo quando richiesto", async () => {
    render(<App />);
    const toggle = screen.getByRole("button", { name: "Filtri" });

    expect(screen.queryByRole("option", { name: "Tutte le categorie" })).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.getByRole("option", { name: "Tutte le categorie" })).toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });
});
