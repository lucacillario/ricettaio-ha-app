export type Difficulty = "easy" | "medium" | "hard";

export interface Category {
  id: string;
  name: string;
  slug: string;
  color: string | null;
  sort_order: number;
}

export interface Ingredient {
  id: string;
  group: string | null;
  name: string;
  quantity: string | null;
  unit: string | null;
  quantity_text: string | null;
  preparation: string | null;
  optional: boolean;
  scalable: boolean;
  sort_order: number;
  original_text: string | null;
}

export interface RecipeStep {
  id: string;
  title: string | null;
  instruction: string;
  duration_minutes: number | null;
  temperature_celsius: number | null;
  sort_order: number;
}

export interface RecipeSource {
  type: "manual" | "ai" | "website" | "video" | "book" | "other";
  url?: string | null;
  title?: string | null;
  author?: string | null;
  accessed_at?: string | null;
  license_note?: string | null;
}

export interface RecipeInput {
  title: string;
  description: string | null;
  category_id: string | null;
  cuisine: string | null;
  difficulty: Difficulty | null;
  base_servings: string;
  serving_unit: string;
  prep_time_minutes: number | null;
  cook_time_minutes: number | null;
  rest_time_minutes: number | null;
  ingredients: Ingredient[];
  steps: RecipeStep[];
  equipment: string[];
  tags: string[];
  dietary_labels: string[];
  allergens: string[];
  notes: string | null;
  source: RecipeSource | null;
  favorite: boolean;
}

export interface Recipe extends RecipeInput {
  id: string;
  schema_version: number;
  slug: string;
  has_cover: boolean;
  revision: number;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface RecipeSummary {
  id: string;
  title: string;
  slug: string;
  description: string | null;
  category_id: string | null;
  category_name: string | null;
  difficulty: Difficulty | null;
  base_servings: string;
  serving_unit: string;
  total_time_minutes: number | null;
  tags: string[];
  favorite: boolean;
  has_cover: boolean;
  revision: number;
  updated_at: string;
  deleted_at: string | null;
}

export interface RecipePage {
  items: RecipeSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatResponse {
  message: string;
  referenced_recipe_ids: string[];
  proposal: AiProposal | null;
}

export interface AiProposal {
  id: string;
  kind: "create" | "update" | "delete";
  recipe_id: string | null;
  base_revision: number | null;
  rationale: string | null;
  preview: RecipeInput | null;
  changed_fields: string[];
  status: "pending" | "applied" | "rejected" | "expired";
}

export interface ProposalApplyResult {
  status: "applied";
  kind: "create" | "update" | "delete";
  recipe: Recipe | null;
}
