import {
  type FormEvent,
  type ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import * as api from "./api";
import type {
  Category,
  AiProposal,
  ChatMessage,
  Ingredient,
  Recipe,
  RecipeInput,
  RecipeStep,
  RecipeSummary,
} from "./types";

type Route =
  | { page: "home" }
  | { page: "new" }
  | { page: "trash" }
  | { page: "detail"; id: string }
  | { page: "edit"; id: string };

const difficultyLabel = { easy: "Facile", medium: "Media", hard: "Impegnativa" };

function parseRoute(): Route {
  const path = window.location.hash.replace(/^#\/?/, "");
  if (path === "new") return { page: "new" };
  if (path === "trash") return { page: "trash" };
  const match = path.match(/^recipes\/([0-9a-f-]+)(\/edit)?$/i);
  if (match) return { page: match[2] ? "edit" : "detail", id: match[1] };
  return { page: "home" };
}

function navigate(path = "") {
  window.location.hash = path ? `#/${path}` : "#/";
}

function useRoute() {
  const [route, setRoute] = useState<Route>(parseRoute);
  useEffect(() => {
    const onChange = () => setRoute(parseRoute());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

function App() {
  const route = useRoute();
  const [categories, setCategories] = useState<Category[]>([]);
  const [chatContext, setChatContext] = useState<{ id?: string; title?: string } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    api.listCategories().then(setCategories).catch(() => setCategories([]));
  }, []);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  let content: ReactNode;
  if (route.page === "new") {
    content = (
      <RecipeEditor
        key="new"
        categories={categories}
        onSaved={(recipe) => {
          setNotice("Ricetta creata");
          navigate(`recipes/${recipe.id}`);
        }}
      />
    );
  } else if (route.page === "detail" || route.page === "edit") {
    content = (
      <RecipeLoader
        key={`${route.page}-${route.id}`}
        id={route.id}
        edit={route.page === "edit"}
        categories={categories}
        onNotice={setNotice}
        onChat={(title) => setChatContext({ id: route.id, title })}
      />
    );
  } else {
    content = (
      <RecipeArchive
        categories={categories}
        trash={route.page === "trash"}
        onNotice={setNotice}
      />
    );
  }

  return (
    <div className="app-shell">
      <Header
        onChat={() => setChatContext({})}
        onNew={() => navigate("new")}
      />
      <main id="main-content">{content}</main>
      {chatContext && (
        <ChatPanel
          recipeId={chatContext.id}
          recipeTitle={chatContext.title}
          onClose={() => setChatContext(null)}
        />
      )}
      {notice && <div className="toast" role="status">{notice}</div>}
    </div>
  );
}

function Header({ onChat, onNew }: { onChat: () => void; onNew: () => void }) {
  return (
    <header className="site-header">
      <button className="brand" onClick={() => navigate()} aria-label="Vai alle ricette">
        <span className="brand-mark" aria-hidden="true">R</span>
        <span>
          <strong>RicettAIo</strong>
          <small>La cucina, come la fai tu.</small>
        </span>
      </button>
      <nav aria-label="Azioni principali">
        <button className="button button-quiet" onClick={onChat}>✦ Chiedi all'AI</button>
        <button className="button button-primary" onClick={onNew}>＋ Nuova ricetta</button>
      </nav>
    </header>
  );
}

function RecipeArchive({
  categories,
  trash,
  onNotice,
}: {
  categories: Category[];
  trash: boolean;
  onNotice: (message: string) => void;
}) {
  const [recipes, setRecipes] = useState<RecipeSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [difficulty, setDifficulty] = useState("");
  const [sort, setSort] = useState("updated_desc");
  const [favorites, setFavorites] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const page = await api.listRecipes({
        q: query,
        category_id: category,
        difficulty,
        favorite: favorites || undefined,
        deleted: trash,
        sort,
      });
      setRecipes(page.items);
      setTotal(page.total);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // Reload when deterministic filters change. Search is submitted explicitly.
  }, [category, difficulty, sort, favorites, trash]);

  const restore = async (id: string) => {
    try {
      await api.restoreRecipe(id);
      onNotice("Ricetta ripristinata");
      await load();
    } catch (reason) {
      setError(errorMessage(reason));
    }
  };

  const importFile = async (file: File | undefined) => {
    if (!file) return;
    if (file.size > 20 * 1024 * 1024) {
      setError("Il file di importazione supera 20 MB");
      return;
    }
    try {
      const archive: unknown = JSON.parse(await file.text());
      if (!window.confirm("Importare le ricette come nuove copie?")) return;
      const result = await api.importArchive(archive);
      onNotice(`${result.imported_recipes} ricette importate`);
      await load();
    } catch (reason) {
      setError(errorMessage(reason));
    }
  };

  return (
    <div className="page archive-page">
      <section className="archive-heading">
        <div>
          <p className="eyebrow">{trash ? "Recupero" : "Il tuo archivio"}</p>
          <h1>{trash ? "Cestino" : "Cosa cuciniamo oggi?"}</h1>
          <p className="lead">
            {trash
              ? "Le ricette eliminate restano qui per 30 giorni."
              : `${total} ${total === 1 ? "ricetta custodita" : "ricette custodite"}`}
          </p>
        </div>
        <div className="archive-tools">
          {!trash && <a className="text-link" href={api.exportUrl} download>Esporta</a>}
          {!trash && (
            <label className="text-link file-link">
              Importa
              <input type="file" accept="application/json,.json" onChange={(event) => void importFile(event.target.files?.[0])} />
            </label>
          )}
          <button className="text-link" onClick={() => navigate(trash ? "" : "trash")}>
            {trash ? "← Torna alle ricette" : "Apri il cestino →"}
          </button>
        </div>
      </section>

      {!trash && (
        <form
          className="search-panel"
          onSubmit={(event) => {
            event.preventDefault();
            void load();
          }}
        >
          <label className="search-box">
            <span aria-hidden="true">⌕</span>
            <span className="sr-only">Cerca nelle ricette</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Cerca una ricetta, un ingrediente, un ricordo…"
            />
            <button type="submit" className="button button-dark">Cerca</button>
          </label>
          <div className="filters" aria-label="Filtri ricette">
            <select value={category} onChange={(event) => setCategory(event.target.value)}>
              <option value="">Tutte le categorie</option>
              {categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
            <select value={difficulty} onChange={(event) => setDifficulty(event.target.value)}>
              <option value="">Ogni difficoltà</option>
              <option value="easy">Facile</option>
              <option value="medium">Media</option>
              <option value="hard">Impegnativa</option>
            </select>
            <select value={sort} onChange={(event) => setSort(event.target.value)}>
              <option value="updated_desc">Modificate di recente</option>
              <option value="title_asc">Titolo A–Z</option>
              <option value="created_desc">Create di recente</option>
              <option value="time_asc">Tempo crescente</option>
            </select>
            <label className="check-filter">
              <input
                type="checkbox"
                checked={favorites}
                onChange={(event) => setFavorites(event.target.checked)}
              />
              Solo preferite
            </label>
          </div>
        </form>
      )}

      {error && <ErrorBanner message={error} retry={load} />}
      {loading ? (
        <LoadingCards />
      ) : recipes.length === 0 ? (
        <EmptyState trash={trash} hasFilters={Boolean(query || category || difficulty || favorites)} />
      ) : (
        <div className="recipe-grid">
          {recipes.map((recipe) => (
            <RecipeCard key={recipe.id} recipe={recipe} trash={trash} onRestore={restore} />
          ))}
        </div>
      )}
    </div>
  );
}

function RecipeCard({
  recipe,
  trash,
  onRestore,
}: {
  recipe: RecipeSummary;
  trash: boolean;
  onRestore: (id: string) => void;
}) {
  return (
    <article className="recipe-card">
      <button
        className="card-image"
        onClick={() => !trash && navigate(`recipes/${recipe.id}`)}
        disabled={trash}
        aria-label={`Apri ${recipe.title}`}
      >
        {recipe.has_cover ? (
          <img src={api.coverUrl(recipe.id, recipe.revision, true)} alt="" />
        ) : (
          <span className="image-placeholder" aria-hidden="true">♨</span>
        )}
        {recipe.category_name && <span className="category-pill">{recipe.category_name}</span>}
        {recipe.favorite && <span className="favorite-mark" aria-label="Preferita">♥</span>}
      </button>
      <div className="card-body">
        <h2>{recipe.title}</h2>
        {recipe.description && <p>{recipe.description}</p>}
        <div className="card-meta">
          {recipe.total_time_minutes !== null && <span>◷ {formatTime(recipe.total_time_minutes)}</span>}
          {recipe.difficulty && <span>{difficultyLabel[recipe.difficulty]}</span>}
        </div>
        {recipe.tags.length > 0 && (
          <div className="tag-row">{recipe.tags.slice(0, 3).map((tag) => <span key={tag}>#{tag}</span>)}</div>
        )}
        {trash ? (
          <button className="button button-secondary card-action" onClick={() => onRestore(recipe.id)}>
            Ripristina
          </button>
        ) : (
          <button className="card-link" onClick={() => navigate(`recipes/${recipe.id}`)}>
            Apri ricetta <span aria-hidden="true">→</span>
          </button>
        )}
      </div>
    </article>
  );
}

function RecipeLoader({
  id,
  edit,
  categories,
  onNotice,
  onChat,
}: {
  id: string;
  edit: boolean;
  categories: Category[];
  onNotice: (message: string) => void;
  onChat: (title: string) => void;
}) {
  const [recipe, setRecipe] = useState<Recipe | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => api.getRecipe(id).then(setRecipe).catch((reason) => setError(errorMessage(reason)));
  useEffect(() => {
    void load();
  }, [id]);
  if (error) return <div className="page"><ErrorBanner message={error} retry={load} /></div>;
  if (!recipe) return <div className="page detail-loading">Carico la ricetta…</div>;
  if (edit) {
    return (
      <RecipeEditor
        key={`${recipe.id}-${recipe.revision}`}
        recipe={recipe}
        categories={categories}
        onSaved={(saved) => {
          onNotice("Modifiche salvate");
          navigate(`recipes/${saved.id}`);
        }}
      />
    );
  }
  return <RecipeDetail recipe={recipe} categories={categories} onNotice={onNotice} onChat={onChat} />;
}

function RecipeDetail({
  recipe,
  categories,
  onNotice,
  onChat,
}: {
  recipe: Recipe;
  categories: Category[];
  onNotice: (message: string) => void;
  onChat: (title: string) => void;
}) {
  const [servings, setServings] = useState(Number(recipe.base_servings));
  const [error, setError] = useState<string | null>(null);
  const category = categories.find((item) => item.id === recipe.category_id);
  const totalTime = [recipe.prep_time_minutes, recipe.cook_time_minutes, recipe.rest_time_minutes]
    .reduce<number>((sum, value) => sum + (value ?? 0), 0);
  const ingredientGroups = useMemo(() => {
    const groups = new Map<string, Ingredient[]>();
    recipe.ingredients.forEach((item) => {
      const key = item.group || "Ingredienti";
      groups.set(key, [...(groups.get(key) ?? []), item]);
    });
    return [...groups.entries()];
  }, [recipe.ingredients]);

  const remove = async () => {
    if (!window.confirm(`Spostare “${recipe.title}” nel cestino per 30 giorni?`)) return;
    try {
      await api.deleteRecipe(recipe.id, recipe.revision);
      onNotice("Ricetta spostata nel cestino");
      navigate();
    } catch (reason) {
      setError(errorMessage(reason));
    }
  };

  const duplicate = async () => {
    try {
      const copy = await api.duplicateRecipe(recipe.id);
      onNotice("Copia creata");
      navigate(`recipes/${copy.id}/edit`);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  };

  return (
    <div className="page detail-page">
      <button className="back-link" onClick={() => navigate()}>← Tutte le ricette</button>
      {error && <ErrorBanner message={error} />}
      <article>
        <header className="detail-hero">
          <div className="detail-copy">
            <div className="detail-pills">
              {category && <span>{category.name}</span>}
              {recipe.difficulty && <span>{difficultyLabel[recipe.difficulty]}</span>}
              {recipe.favorite && <span>♥ Preferita</span>}
            </div>
            <h1>{recipe.title}</h1>
            {recipe.description && <p className="lead">{recipe.description}</p>}
            <div className="detail-actions">
              <button className="button button-primary" onClick={() => onChat(recipe.title)}>✦ Chiedi all'AI</button>
              <button className="button button-secondary" onClick={() => navigate(`recipes/${recipe.id}/edit`)}>Modifica</button>
              <button className="button button-quiet" onClick={duplicate}>Duplica</button>
              <button className="button button-danger" onClick={remove}>Elimina</button>
            </div>
          </div>
          <div className="detail-cover">
            {recipe.has_cover ? (
              <img src={api.coverUrl(recipe.id, recipe.revision)} alt={`Copertina di ${recipe.title}`} />
            ) : (
              <span className="image-placeholder large" aria-hidden="true">♨</span>
            )}
          </div>
        </header>

        <section className="facts" aria-label="Informazioni ricetta">
          <div><small>Preparazione</small><strong>{formatOptionalTime(recipe.prep_time_minutes)}</strong></div>
          <div><small>Cottura</small><strong>{formatOptionalTime(recipe.cook_time_minutes)}</strong></div>
          <div><small>Tempo totale</small><strong>{formatTime(totalTime)}</strong></div>
          <div><small>Porzioni base</small><strong>{recipe.base_servings} {recipe.serving_unit}</strong></div>
        </section>

        <div className="recipe-columns">
          <aside className="ingredients-panel">
            <div className="section-title-row">
              <h2>Ingredienti</h2>
              <label className="servings-control">
                <span>Porzioni</span>
                <input
                  type="number"
                  min="0.25"
                  step="0.25"
                  value={servings}
                  onChange={(event) => setServings(Math.max(0.25, Number(event.target.value)))}
                />
              </label>
            </div>
            {ingredientGroups.map(([group, items]) => (
              <div className="ingredient-group" key={group}>
                {ingredientGroups.length > 1 && <h3>{group}</h3>}
                <ul>
                  {items.map((item) => (
                    <li key={item.id}>
                      <span className="ingredient-quantity">
                        {scaledQuantity(item, servings, Number(recipe.base_servings))}
                      </span>
                      <span><strong>{item.name}</strong>{item.preparation ? `, ${item.preparation}` : ""}{item.optional ? " (facoltativo)" : ""}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </aside>

          <section className="steps-panel">
            <h2>Preparazione</h2>
            <ol className="steps-list">
              {recipe.steps.map((step, index) => (
                <li key={step.id}>
                  <span className="step-number">{String(index + 1).padStart(2, "0")}</span>
                  <div>
                    {step.title && <h3>{step.title}</h3>}
                    <p>{step.instruction}</p>
                    {(step.duration_minutes !== null || step.temperature_celsius !== null) && (
                      <small>
                        {step.duration_minutes !== null && `◷ ${step.duration_minutes} min`}
                        {step.duration_minutes !== null && step.temperature_celsius !== null && " · "}
                        {step.temperature_celsius !== null && `${step.temperature_celsius} °C`}
                      </small>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </section>
        </div>

        {(recipe.notes || recipe.tags.length > 0 || recipe.equipment.length > 0) && (
          <section className="recipe-notes">
            {recipe.notes && <div><h2>Note</h2><p>{recipe.notes}</p></div>}
            {recipe.equipment.length > 0 && <div><h2>Attrezzatura</h2><p>{recipe.equipment.join(", ")}</p></div>}
            {recipe.tags.length > 0 && <div className="tag-row">{recipe.tags.map((tag) => <span key={tag}>#{tag}</span>)}</div>}
          </section>
        )}
      </article>
    </div>
  );
}

function RecipeEditor({
  recipe,
  categories,
  onSaved,
}: {
  recipe?: Recipe;
  categories: Category[];
  onSaved: (recipe: Recipe) => void;
}) {
  const [form, setForm] = useState<RecipeInput>(() => recipeToInput(recipe));
  const [cover, setCover] = useState<File | null>(null);
  const [removeExistingCover, setRemoveExistingCover] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aiPrompt, setAiPrompt] = useState("");
  const [drafting, setDrafting] = useState(false);
  const dirty = useRef(false);

  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (dirty.current) event.preventDefault();
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, []);

  const update = <K extends keyof RecipeInput>(key: K, value: RecipeInput[K]) => {
    dirty.current = true;
    setForm((current) => ({ ...current, [key]: value }));
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      let saved = recipe
        ? await api.updateRecipe(recipe.id, form, recipe.revision)
        : await api.createRecipe(form);
      if (removeExistingCover && saved.has_cover) saved = await api.deleteCover(saved.id);
      if (cover) saved = await api.uploadCover(saved.id, cover);
      dirty.current = false;
      onSaved(saved);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setSaving(false);
    }
  };

  const generateDraft = async () => {
    if (aiPrompt.trim().length < 3) return;
    setDrafting(true);
    setError(null);
    try {
      const draft = await api.createDraft(aiPrompt);
      setForm(draft);
      dirty.current = true;
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setDrafting(false);
    }
  };

  return (
    <div className="page editor-page">
      <button className="back-link" onClick={() => navigate(recipe ? `recipes/${recipe.id}` : "")}>← Annulla</button>
      <div className="editor-heading">
        <div>
          <p className="eyebrow">{recipe ? "Modifica" : "Nuova ricetta"}</p>
          <h1>{recipe ? recipe.title : "Aggiungi qualcosa di buono"}</h1>
        </div>
      </div>
      {!recipe && (
        <section className="ai-draft-box">
          <div><strong>✦ Parti da un'idea</strong><p>L'AI prepara una bozza che potrai correggere prima di salvarla.</p></div>
          <div className="ai-draft-input">
            <input value={aiPrompt} onChange={(event) => setAiPrompt(event.target.value)} placeholder="Es. una torta semplice con mele e yogurt" />
            <button className="button button-dark" type="button" onClick={generateDraft} disabled={drafting}>{drafting ? "Creo…" : "Crea bozza"}</button>
          </div>
        </section>
      )}
      {error && <ErrorBanner message={error} />}
      <form className="recipe-form" onSubmit={save}>
        <FormSection number="01" title="L'essenziale">
          <div className="field-grid two">
            <Field label="Titolo *" wide>
              <input required maxLength={200} value={form.title} onChange={(event) => update("title", event.target.value)} placeholder="Pasta e ceci della nonna" />
            </Field>
            <Field label="Descrizione" wide>
              <textarea rows={3} value={form.description ?? ""} onChange={(event) => update("description", nullIfEmpty(event.target.value))} placeholder="Una breve storia o descrizione…" />
            </Field>
            <Field label="Categoria">
              <select value={form.category_id ?? ""} onChange={(event) => update("category_id", event.target.value || null)}>
                <option value="">Nessuna categoria</option>
                {categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </Field>
            <Field label="Cucina">
              <input value={form.cuisine ?? ""} onChange={(event) => update("cuisine", nullIfEmpty(event.target.value))} placeholder="Italiana" />
            </Field>
            <Field label="Difficoltà">
              <select value={form.difficulty ?? ""} onChange={(event) => update("difficulty", (event.target.value || null) as RecipeInput["difficulty"])}>
                <option value="">Non indicata</option><option value="easy">Facile</option><option value="medium">Media</option><option value="hard">Impegnativa</option>
              </select>
            </Field>
            <label className="favorite-toggle"><input type="checkbox" checked={form.favorite} onChange={(event) => update("favorite", event.target.checked)} /> ♥ Segna come preferita</label>
          </div>
        </FormSection>

        <FormSection number="02" title="Dosi e tempi">
          <div className="field-grid four">
            <Field label="Quantità base *"><input required type="number" min="0.25" step="0.25" value={form.base_servings} onChange={(event) => update("base_servings", event.target.value)} /></Field>
            <Field label="Unità *"><input required value={form.serving_unit} onChange={(event) => update("serving_unit", event.target.value)} placeholder="persone" /></Field>
            <Field label="Preparazione (min)"><NumberInput value={form.prep_time_minutes} onChange={(value) => update("prep_time_minutes", value)} /></Field>
            <Field label="Cottura (min)"><NumberInput value={form.cook_time_minutes} onChange={(value) => update("cook_time_minutes", value)} /></Field>
            <Field label="Riposo (min)"><NumberInput value={form.rest_time_minutes} onChange={(value) => update("rest_time_minutes", value)} /></Field>
          </div>
        </FormSection>

        <FormSection number="03" title="Ingredienti">
          <div className="repeat-list">
            {form.ingredients.map((item, index) => (
              <div className="ingredient-edit-row" key={item.id}>
                <span className="drag-index">{index + 1}</span>
                <input aria-label={`Ingrediente ${index + 1}`} required value={item.name} onChange={(event) => updateIngredient(index, "name", event.target.value, form, update)} placeholder="Ingrediente" />
                <input aria-label="Quantità" value={item.quantity ?? ""} onChange={(event) => updateIngredient(index, "quantity", nullIfEmpty(event.target.value), form, update)} placeholder="Quantità" inputMode="decimal" />
                <input aria-label="Unità" value={item.unit ?? ""} onChange={(event) => updateIngredient(index, "unit", nullIfEmpty(event.target.value), form, update)} placeholder="g, ml…" />
                <input aria-label="Nota quantità" value={item.quantity_text ?? ""} onChange={(event) => updateIngredient(index, "quantity_text", nullIfEmpty(event.target.value), form, update)} placeholder="oppure q.b." />
                <input aria-label="Preparazione ingrediente" value={item.preparation ?? ""} onChange={(event) => updateIngredient(index, "preparation", nullIfEmpty(event.target.value), form, update)} placeholder="tritato, scolato…" />
                <button type="button" className="icon-button" aria-label="Rimuovi ingrediente" onClick={() => update("ingredients", form.ingredients.filter((_, itemIndex) => itemIndex !== index))}>×</button>
              </div>
            ))}
          </div>
          <button type="button" className="add-row" onClick={() => update("ingredients", [...form.ingredients, emptyIngredient()])}>＋ Aggiungi ingrediente</button>
        </FormSection>

        <FormSection number="04" title="Preparazione">
          <div className="repeat-list">
            {form.steps.map((step, index) => (
              <div className="step-edit-row" key={step.id}>
                <span className="step-number">{String(index + 1).padStart(2, "0")}</span>
                <div>
                  <input aria-label={`Titolo passaggio ${index + 1}`} value={step.title ?? ""} onChange={(event) => updateStep(index, "title", nullIfEmpty(event.target.value), form, update)} placeholder="Titolo facoltativo" />
                  <textarea aria-label={`Istruzione passaggio ${index + 1}`} required rows={3} value={step.instruction} onChange={(event) => updateStep(index, "instruction", event.target.value, form, update)} placeholder="Descrivi il passaggio…" />
                  <div className="inline-fields">
                    <label>Minuti <NumberInput value={step.duration_minutes} onChange={(value) => updateStep(index, "duration_minutes", value, form, update)} /></label>
                    <label>°C <NumberInput value={step.temperature_celsius} onChange={(value) => updateStep(index, "temperature_celsius", value, form, update)} /></label>
                  </div>
                </div>
                <button type="button" className="icon-button" aria-label="Rimuovi passaggio" onClick={() => update("steps", form.steps.filter((_, itemIndex) => itemIndex !== index))}>×</button>
              </div>
            ))}
          </div>
          <button type="button" className="add-row" onClick={() => update("steps", [...form.steps, emptyStep()])}>＋ Aggiungi passaggio</button>
        </FormSection>

        <FormSection number="05" title="Dettagli e copertina">
          <div className="field-grid two">
            <Field label="Tag (separati da virgola)"><input value={form.tags.join(", ")} onChange={(event) => update("tags", commaList(event.target.value))} placeholder="vegetariano, veloce" /></Field>
            <Field label="Attrezzatura (separata da virgola)"><input value={form.equipment.join(", ")} onChange={(event) => update("equipment", commaList(event.target.value))} placeholder="pentola, frullatore" /></Field>
            <Field label="Note" wide><textarea rows={4} value={form.notes ?? ""} onChange={(event) => update("notes", nullIfEmpty(event.target.value))} /></Field>
            <Field label="Immagine di copertina" wide>
              <input type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => { setCover(event.target.files?.[0] ?? null); dirty.current = true; }} />
              <small>JPEG, PNG o WebP; massimo 10 MB.</small>
              {recipe?.has_cover && <label className="check-filter"><input type="checkbox" checked={removeExistingCover} onChange={(event) => setRemoveExistingCover(event.target.checked)} /> Rimuovi la copertina attuale</label>}
            </Field>
          </div>
        </FormSection>

        <div className="form-actions">
          <button className="button button-quiet" type="button" onClick={() => navigate(recipe ? `recipes/${recipe.id}` : "")}>Annulla</button>
          <button className="button button-primary" type="submit" disabled={saving}>{saving ? "Salvataggio…" : "Salva ricetta"}</button>
        </div>
      </form>
    </div>
  );
}

function ChatPanel({ recipeId, recipeTitle, onClose }: { recipeId?: string; recipeTitle?: string; onClose: () => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [proposal, setProposal] = useState<AiProposal | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [messages]);

  const send = async (event: FormEvent) => {
    event.preventDefault();
    const content = text.trim();
    if (!content || waiting) return;
    const next: ChatMessage[] = [...messages, { role: "user", content }];
    setMessages(next);
    setText("");
    setWaiting(true);
    setError(null);
    try {
      const response = await api.chat(next, recipeId);
      setMessages([...next, { role: "assistant", content: response.message }]);
      setProposal(response.proposal);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setWaiting(false);
    }
  };

  const applyProposal = async () => {
    if (!proposal) return;
    setWaiting(true);
    setError(null);
    try {
      const result = await api.applyProposal(proposal);
      onClose();
      if (result.recipe) navigate(`recipes/${result.recipe.id}`);
      else navigate();
      window.location.reload();
    } catch (reason) {
      setError(errorMessage(reason));
      setWaiting(false);
    }
  };

  const rejectProposal = async () => {
    if (!proposal) return;
    try {
      await api.rejectProposal(proposal);
      setProposal(null);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  };

  return (
    <div className="chat-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}>
      <aside className="chat-panel" role="dialog" aria-modal="true" aria-labelledby="chat-title">
        <header>
          <div><p className="eyebrow">Assistente effimero</p><h2 id="chat-title">{recipeTitle ? `Parliamo di ${recipeTitle}` : "Chiedi al tuo ricettario"}</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="Chiudi e cancella la chat">×</button>
        </header>
        <div className="chat-messages">
          {messages.length === 0 && (
            <div className="chat-welcome"><span>✦</span><h3>Come posso aiutarti?</h3><p>{recipeId ? "Posso spiegare, adattare o proporti una variante della ricetta." : "Cercherò prima tra le tue ricette e ti dirò quali ho consultato."}</p></div>
          )}
          {messages.map((message, index) => <div key={index} className={`chat-message ${message.role}`}>{message.content}</div>)}
          {proposal && (
            <div className={`proposal-card ${proposal.kind}`}>
              <strong>{proposalTitle(proposal.kind)}</strong>
              {proposal.preview && <h3>{proposal.preview.title}</h3>}
              {proposal.rationale && <p>{proposal.rationale}</p>}
              {proposal.changed_fields.length > 0 && (
                <small>Campi interessati: {proposal.changed_fields.map(fieldLabel).join(", ")}</small>
              )}
              <div>
                <button className="button button-primary" onClick={() => void applyProposal()} disabled={waiting}>Conferma</button>
                <button className="button button-quiet" onClick={() => void rejectProposal()} disabled={waiting}>Scarta</button>
              </div>
            </div>
          )}
          {waiting && <div className="chat-message assistant typing">Sto pensando…</div>}
          {error && <div className="chat-error">{error}</div>}
          <div ref={endRef} />
        </div>
        <form className="chat-compose" onSubmit={send}>
          <textarea rows={2} value={text} onChange={(event) => setText(event.target.value)} placeholder="Scrivi qui…" aria-label="Messaggio" />
          <button className="button button-primary" disabled={waiting || !text.trim()}>Invia</button>
        </form>
        <small className="chat-privacy">Chiudendo questa finestra la conversazione viene cancellata.</small>
      </aside>
    </div>
  );
}

function FormSection({ number, title, children }: { number: string; title: string; children: ReactNode }) {
  return <section className="form-section"><header><span>{number}</span><h2>{title}</h2></header><div className="form-section-body">{children}</div></section>;
}

function Field({ label, children, wide = false }: { label: string; children: ReactNode; wide?: boolean }) {
  return <label className={`field ${wide ? "wide" : ""}`}><span>{label}</span>{children}</label>;
}

function NumberInput({ value, onChange }: { value: number | null; onChange: (value: number | null) => void }) {
  return <input type="number" min="0" value={value ?? ""} onChange={(event) => onChange(event.target.value === "" ? null : Number(event.target.value))} />;
}

function ErrorBanner({ message, retry }: { message: string; retry?: () => void }) {
  return <div className="error-banner" role="alert"><span>{message}</span>{retry && <button onClick={retry}>Riprova</button>}</div>;
}

function LoadingCards() {
  return <div className="recipe-grid" aria-label="Caricamento">{[1, 2, 3].map((item) => <div className="recipe-card skeleton" key={item}><div className="card-image" /><div className="card-body"><i /><i /><i /></div></div>)}</div>;
}

function EmptyState({ trash, hasFilters }: { trash: boolean; hasFilters: boolean }) {
  return <div className="empty-state"><span aria-hidden="true">♨</span><h2>{trash ? "Il cestino è vuoto" : hasFilters ? "Nessuna ricetta trovata" : "Il ricettario ti aspetta"}</h2><p>{trash ? "Le ricette eliminate compariranno qui." : hasFilters ? "Prova a cambiare ricerca o filtri." : "Comincia aggiungendo la prima ricetta, a mano o con l'aiuto dell'AI."}</p>{!trash && !hasFilters && <button className="button button-primary" onClick={() => navigate("new")}>Aggiungi la prima ricetta</button>}</div>;
}

function recipeToInput(recipe?: Recipe): RecipeInput {
  if (recipe) {
    return {
      title: recipe.title,
      description: recipe.description,
      category_id: recipe.category_id,
      cuisine: recipe.cuisine,
      difficulty: recipe.difficulty,
      base_servings: recipe.base_servings,
      serving_unit: recipe.serving_unit,
      prep_time_minutes: recipe.prep_time_minutes,
      cook_time_minutes: recipe.cook_time_minutes,
      rest_time_minutes: recipe.rest_time_minutes,
      ingredients: recipe.ingredients,
      steps: recipe.steps,
      equipment: recipe.equipment,
      tags: recipe.tags,
      dietary_labels: recipe.dietary_labels,
      allergens: recipe.allergens,
      notes: recipe.notes,
      source: recipe.source,
      favorite: recipe.favorite,
    };
  }
  return {
    title: "", description: null, category_id: null, cuisine: null, difficulty: null,
    base_servings: "4", serving_unit: "persone", prep_time_minutes: null,
    cook_time_minutes: null, rest_time_minutes: null, ingredients: [emptyIngredient()],
    steps: [emptyStep()], equipment: [], tags: [], dietary_labels: [], allergens: [],
    notes: null, source: { type: "manual" }, favorite: false,
  };
}

function emptyIngredient(): Ingredient {
  return { id: crypto.randomUUID(), group: null, name: "", quantity: null, unit: null, quantity_text: null, preparation: null, optional: false, scalable: true, sort_order: 0, original_text: null };
}

function emptyStep(): RecipeStep {
  return { id: crypto.randomUUID(), title: null, instruction: "", duration_minutes: null, temperature_celsius: null, sort_order: 0 };
}

function updateIngredient<K extends keyof Ingredient>(index: number, key: K, value: Ingredient[K], form: RecipeInput, update: <P extends keyof RecipeInput>(key: P, value: RecipeInput[P]) => void) {
  update("ingredients", form.ingredients.map((item, itemIndex) => itemIndex === index ? { ...item, [key]: value } : item));
}

function updateStep<K extends keyof RecipeStep>(index: number, key: K, value: RecipeStep[K], form: RecipeInput, update: <P extends keyof RecipeInput>(key: P, value: RecipeInput[P]) => void) {
  update("steps", form.steps.map((item, itemIndex) => itemIndex === index ? { ...item, [key]: value } : item));
}

function commaList(value: string) { return value.split(",").map((item) => item.trim()).filter(Boolean); }
function nullIfEmpty(value: string) { return value.trim() ? value : null; }
function formatOptionalTime(value: number | null) { return value === null ? "—" : formatTime(value); }
function formatTime(minutes: number) { if (minutes < 60) return `${minutes} min`; const hours = Math.floor(minutes / 60); const rest = minutes % 60; return rest ? `${hours} h ${rest} min` : `${hours} h`; }
function errorMessage(reason: unknown) { return reason instanceof Error ? reason.message : "Si è verificato un errore inatteso"; }
function proposalTitle(kind: AiProposal["kind"]) { return kind === "create" ? "Nuova ricetta proposta" : kind === "update" ? "Modifica proposta" : "Eliminazione proposta"; }
function fieldLabel(field: string) { return ({ title: "titolo", description: "descrizione", ingredients: "ingredienti", steps: "passaggi", notes: "note", tags: "tag", difficulty: "difficoltà", base_servings: "porzioni", category_id: "categoria" } as Record<string, string>)[field] ?? field; }

function scaledQuantity(item: Ingredient, servings: number, baseServings: number) {
  if (item.quantity_text) return item.quantity_text;
  if (item.quantity === null) return "";
  const raw = Number(item.quantity) * (item.scalable ? servings / baseServings : 1);
  const rounded = Math.round(raw * 100) / 100;
  return `${new Intl.NumberFormat("it-IT", { maximumFractionDigits: 2 }).format(rounded)}${item.unit ? ` ${item.unit}` : ""}`;
}

export default App;
