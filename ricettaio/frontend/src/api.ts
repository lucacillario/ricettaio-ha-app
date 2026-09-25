import type {
  Category,
  AiProposal,
  ChatMessage,
  ChatResponse,
  Recipe,
  RecipeInput,
  RecipePage,
  ProposalApplyResult,
} from "./types";

const API = "api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}/${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = `Errore ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      // Keep the generic HTTP error.
    }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export interface RecipeFilters {
  q?: string;
  category_id?: string;
  difficulty?: string;
  favorite?: boolean;
  deleted?: boolean;
  sort?: string;
}

export async function listRecipes(filters: RecipeFilters = {}): Promise<RecipePage> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  return request<RecipePage>(`recipes?${params.toString()}`);
}

export const listCategories = () => request<Category[]>("categories");
export const getRecipe = (id: string) => request<Recipe>(`recipes/${id}`);
export const createRecipe = (payload: RecipeInput) =>
  request<Recipe>("recipes", { method: "POST", body: JSON.stringify(payload) });
export const updateRecipe = (id: string, payload: RecipeInput, revision: number) =>
  request<Recipe>(`recipes/${id}`, {
    method: "PUT",
    body: JSON.stringify({ ...payload, revision }),
  });
export const duplicateRecipe = (id: string) =>
  request<Recipe>(`recipes/${id}/duplicate`, { method: "POST" });
export const deleteRecipe = (id: string, revision: number) =>
  request<void>(`recipes/${id}`, {
    method: "DELETE",
    body: JSON.stringify({ revision }),
  });
export const restoreRecipe = (id: string) =>
  request<Recipe>(`recipes/${id}/restore`, { method: "POST" });

export async function uploadCover(id: string, image: File): Promise<Recipe> {
  const data = new FormData();
  data.append("image", image);
  return request<Recipe>(`recipes/${id}/cover`, { method: "POST", body: data });
}

export const deleteCover = (id: string) =>
  request<Recipe>(`recipes/${id}/cover`, { method: "DELETE" });

export const coverUrl = (id: string, revision: number, thumbnail = false) =>
  `${API}/recipes/${id}/cover?thumbnail=${thumbnail}&v=${revision}`;

export const chat = (messages: ChatMessage[], recipeId?: string) =>
  request<ChatResponse>("ai/chat", {
    method: "POST",
    body: JSON.stringify({ messages, recipe_id: recipeId ?? null }),
  });

export const createDraft = (prompt: string) =>
  request<RecipeInput>("ai/drafts", {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });

export const exportUrl = `${API}/export`;

export const importArchive = (archive: unknown) =>
  request<{ imported_recipes: number; imported_categories: number }>("import", {
    method: "POST",
    body: JSON.stringify(archive),
  });

export const applyProposal = (proposal: AiProposal) =>
  request<ProposalApplyResult>(`ai/proposals/${proposal.id}/apply`, { method: "POST" });

export const rejectProposal = (proposal: AiProposal) =>
  request<void>(`ai/proposals/${proposal.id}`, { method: "DELETE" });
