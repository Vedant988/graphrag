import { useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  BarChart3,
  BrainCircuit,
  CheckCircle2,
  Database,
  Gauge,
  GitBranchPlus,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { RxHamburgerMenu } from "react-icons/rx";

import SideMenu from "@/components/SideMenu";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const defaultQuestion =
  "In Dhritarashtra's lament to Sanjaya, what specific weapon did Aswatthaman use against the embryo of Virata's daughter, and what consequence followed?";

const headlineMetrics = [
  {
    label: "GraphRAG vs Basic RAG",
    value: "Pending live run",
    hint: "Token reduction % will surface here after benchmark execution.",
  },
  {
    label: "Cost Per Query",
    value: "Pending pricing calc",
    hint: "Each pipeline will report prompt + completion cost.",
  },
  {
    label: "Latency",
    value: "Pending timing run",
    hint: "End-to-end response time will be captured side by side.",
  },
  {
    label: "Accuracy",
    value: "Judge + BERTScore",
    hint: "LLM-as-a-Judge PASS/FAIL and BERTScore F1 land here next.",
  },
];

const proofPoints = [
  {
    title: "Three pipelines, one question",
    body: "LLM-Only, Basic RAG, and GraphRAG answer the same query on the same corpus so the comparison stays honest.",
    icon: BrainCircuit,
  },
  {
    title: "Path B customization",
    body: "This dashboard is built for retriever tuning, prompt tuning, schema extension, and side-by-side outcome measurement.",
    icon: GitBranchPlus,
  },
  {
    title: "Benchmark-ready metrics",
    body: "Tokens, cost, latency, LLM-as-a-Judge, and BERTScore are already laid out so we can wire the evaluation phase directly into this surface.",
    icon: BarChart3,
  },
];

const pipelineCards = [
  {
    name: "LLM-Only",
    accent: "from-slate-500/30 to-slate-700/10",
    badgeClass:
      "border-slate-500/30 bg-slate-500/10 text-slate-700 dark:text-slate-200",
    borderClass: "border-slate-300/80 dark:border-slate-700/70",
    summary:
      "Worst-case baseline. No retrieval, no grounding, just the model answering from prior knowledge.",
    answer:
      "Ready for wiring. This panel will show the raw answer, token load, and how quickly a pure prompt-only pipeline drifts when the question requires grounded reasoning.",
    metrics: [
      { label: "Tokens", value: "--", hint: "Prompt + completion" },
      { label: "Cost", value: "--", hint: "Per query" },
      { label: "Latency", value: "--", hint: "End-to-end" },
      { label: "Accuracy", value: "--", hint: "Judge + BERTScore" },
    ],
  },
  {
    name: "Basic RAG",
    accent: "from-amber-400/25 to-orange-500/10",
    badgeClass:
      "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-200",
    borderClass: "border-amber-300/70 dark:border-amber-900/60",
    summary:
      "Embedding search plus an LLM. Strong on similarity, weaker when the answer depends on multi-hop relationships.",
    answer:
      "Ready for wiring. This panel will show retrieved-context synthesis, with metrics that make chunk count, token spend, and answer fidelity easy to compare against GraphRAG.",
    metrics: [
      { label: "Tokens", value: "--", hint: "Retrieval + synthesis" },
      { label: "Cost", value: "--", hint: "Per query" },
      { label: "Latency", value: "--", hint: "Vector search + LLM" },
      { label: "Accuracy", value: "--", hint: "Judge + BERTScore" },
    ],
  },
  {
    name: "GraphRAG",
    accent: "from-orange-500/30 to-emerald-500/10",
    badgeClass:
      "border-orange-500/40 bg-orange-500/10 text-orange-700 dark:text-orange-200",
    borderClass: "border-orange-300/80 dark:border-orange-800/70",
    summary:
      "Entity-relationship reasoning over TigerGraph. Built to answer with fewer tokens and better structural faithfulness.",
    answer:
      "Ready for wiring. This panel will show the graph-grounded final answer, plus benchmark metrics that prove whether graph reasoning beats similarity-only retrieval.",
    metrics: [
      { label: "Tokens", value: "--", hint: "Focused graph prompt" },
      { label: "Cost", value: "--", hint: "Per query" },
      { label: "Latency", value: "--", hint: "Retriever + answer" },
      { label: "Accuracy", value: "--", hint: "Judge + BERTScore" },
    ],
  },
];

const Comparison = () => {
  const [showSidebar, setShowSidebar] = useState(true);
  const [query, setQuery] = useState(defaultQuestion);
  const [submittedQuery, setSubmittedQuery] = useState(defaultQuestion);

  const selectedGraph =
    typeof window !== "undefined"
      ? sessionStorage.getItem("selectedGraph") || "gemini_1_0"
      : "gemini_1_0";
  const ragPattern =
    typeof window !== "undefined"
      ? sessionStorage.getItem("ragPattern") || "Path B"
      : "Path B";

  const handleRunPreview = () => {
    const nextQuery = query.trim() || defaultQuestion;
    setSubmittedQuery(nextQuery);
  };

  return (
    <div className="flex justify-between boxA bounce-3">
      {showSidebar ? <SideMenu setGetConversationId={() => undefined} /> : null}
      <button
        className="absolute left-0 top-0 z-20 p-1 text-xl"
        onClick={() => setShowSidebar((prev) => !prev)}
        aria-label="Toggle navigation"
        type="button"
      >
        <RxHamburgerMenu />
      </button>

      <main className="min-h-screen flex-1 overflow-y-auto border-l border-gray-200 bg-background dark:border-[#3D3D3D]">
        <div className="relative overflow-hidden">
          <div className="pointer-events-none absolute -left-16 top-14 h-48 w-48 rounded-full bg-orange-500/15 blur-3xl" />
          <div className="pointer-events-none absolute right-0 top-20 h-64 w-64 rounded-full bg-amber-500/10 blur-3xl" />

          <div className="mx-auto flex w-full max-w-7xl flex-col gap-8 px-4 pb-10 pt-16 md:px-8">
            <section className="relative overflow-hidden rounded-[28px] border border-gray-200/80 bg-card/90 p-6 shadow-sm dark:border-[#3D3D3D] dark:bg-[#241c1f]/90 md:p-8">
              <div className="pointer-events-none absolute inset-x-0 top-0 h-1 gradient" />
              <div className="grid gap-8 xl:grid-cols-[1.6fr_1fr]">
                <div className="space-y-5">
                  <div className="flex flex-wrap gap-3 text-xs uppercase tracking-[0.2em] text-muted-foreground">
                    <span className="rounded-full border border-orange-500/30 bg-orange-500/10 px-3 py-1 font-semibold text-orange-700 dark:text-orange-200">
                      Round 1 Comparison Dashboard
                    </span>
                    <span className="rounded-full border border-gray-300 px-3 py-1 font-semibold dark:border-[#3D3D3D]">
                      {ragPattern}
                    </span>
                    <span className="rounded-full border border-gray-300 px-3 py-1 font-semibold dark:border-[#3D3D3D]">
                      Graph: {selectedGraph}
                    </span>
                  </div>

                  <div className="space-y-3">
                    <h1 className="Urbane-Medium max-w-4xl text-4xl leading-tight text-black dark:text-white md:text-5xl">
                      One query in. Three pipelines out. The cost story becomes
                      impossible to ignore.
                    </h1>
                    <p className="max-w-4xl text-base leading-7 text-muted-foreground md:text-lg">
                      LLMs burn through thousands of tokens to answer complex
                      questions. Basic RAG helps by retrieving similar chunks,
                      but it still struggles when the answer depends on
                      relationships between entities. GraphRAG organizes those
                      entities, walks the graph, and gives the model a sharper
                      prompt instead of a giant context dump.
                    </p>
                    <p className="max-w-4xl text-base leading-7 text-muted-foreground md:text-lg">
                      The bet for this hackathon is simple: GraphRAG should beat
                      Basic RAG on token efficiency, latency, and grounded
                      answer quality. This page is where we prove it.
                    </p>
                  </div>

                  <div className="flex flex-wrap gap-3">
                    <Button
                      asChild
                      className="gradient h-11 border-0 px-5 text-white hover:opacity-95"
                    >
                      <Link to="/chat">
                        Open Chat
                        <ArrowRight className="ml-2 h-4 w-4" />
                      </Link>
                    </Button>
                    <div className="flex items-center gap-2 rounded-full border border-gray-300 px-4 py-2 text-sm text-muted-foreground dark:border-[#3D3D3D]">
                      <ShieldCheck className="h-4 w-4 text-orange-500" />
                      Validation and benchmark execution wire in next phase.
                    </div>
                  </div>
                </div>

                <div className="grid gap-4 rounded-[24px] border border-gray-200/80 bg-background/70 p-5 dark:border-[#3D3D3D] dark:bg-black/10">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                        Benchmark Results Summary
                      </p>
                      <h2 className="mt-2 text-2xl font-semibold text-black dark:text-white">
                        The headline metrics are already staged.
                      </h2>
                    </div>
                    <div className="rounded-2xl border border-orange-500/30 bg-orange-500/10 p-3">
                      <Gauge className="h-5 w-5 text-orange-600 dark:text-orange-200" />
                    </div>
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2">
                    {headlineMetrics.map((metric) => (
                      <div
                        key={metric.label}
                        className="rounded-2xl border border-gray-200 bg-card px-4 py-4 dark:border-[#3D3D3D] dark:bg-[#2a2024]"
                      >
                        <p className="text-sm text-muted-foreground">
                          {metric.label}
                        </p>
                        <p className="mt-2 text-lg font-semibold text-black dark:text-white">
                          {metric.value}
                        </p>
                        <p className="mt-2 text-sm leading-6 text-muted-foreground">
                          {metric.hint}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </section>

            <section className="grid gap-4 lg:grid-cols-3">
              {proofPoints.map((point) => {
                const Icon = point.icon;
                return (
                  <div
                    key={point.title}
                    className="rounded-[24px] border border-gray-200 bg-card p-5 shadow-sm dark:border-[#3D3D3D] dark:bg-[#241c1f]"
                  >
                    <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-orange-500/30 bg-orange-500/10">
                      <Icon className="h-5 w-5 text-orange-600 dark:text-orange-200" />
                    </div>
                    <h3 className="text-xl font-semibold text-black dark:text-white">
                      {point.title}
                    </h3>
                    <p className="mt-3 text-sm leading-6 text-muted-foreground">
                      {point.body}
                    </p>
                  </div>
                );
              })}
            </section>

            <section className="rounded-[28px] border border-gray-200 bg-card p-5 shadow-sm dark:border-[#3D3D3D] dark:bg-[#241c1f] md:p-6">
              <div className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
                <div className="max-w-3xl space-y-2">
                  <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                    Live Comparison
                  </p>
                  <h2 className="text-3xl font-semibold text-black dark:text-white">
                    One benchmark query, rendered side by side.
                  </h2>
                  <p className="text-sm leading-6 text-muted-foreground">
                    This first pass is a themed dashboard shell. It already
                    captures the benchmark framing and the comparison layout so
                    the next phase can focus on retrieval, answer validation,
                    token accounting, and score computation.
                  </p>
                </div>

                <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
                  <div className="flex items-center gap-2 rounded-full border border-gray-300 px-3 py-2 dark:border-[#3D3D3D]">
                    <Database className="h-4 w-4 text-orange-500" />
                    Minimum dataset target: 1M+ tokens
                  </div>
                  <div className="flex items-center gap-2 rounded-full border border-gray-300 px-3 py-2 dark:border-[#3D3D3D]">
                    <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                    Path B customization active
                  </div>
                </div>
              </div>

              <div className="mt-6 grid gap-3 xl:grid-cols-[1fr_auto]">
                <Input
                  className="h-14 rounded-2xl border-gray-300 bg-background px-5 text-base dark:border-[#3D3D3D] dark:bg-[#1c1518]"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      handleRunPreview();
                    }
                  }}
                  placeholder="Ask one benchmark question for all three pipelines..."
                />
                <Button
                  className="gradient h-14 rounded-2xl border-0 px-6 text-white hover:opacity-95"
                  type="button"
                  onClick={handleRunPreview}
                >
                  Preview Benchmark Layout
                  <Sparkles className="ml-2 h-4 w-4" />
                </Button>
              </div>

              <div className="mt-4 rounded-2xl border border-dashed border-orange-500/40 bg-orange-500/[0.06] px-4 py-3 text-sm leading-6 text-muted-foreground">
                Current query preview:
                <span className="ml-2 font-medium text-black dark:text-white">
                  {submittedQuery}
                </span>
              </div>
            </section>

            <section className="grid gap-5 2xl:grid-cols-3">
              {pipelineCards.map((pipeline) => (
                <article
                  key={pipeline.name}
                  className={cn(
                    "overflow-hidden rounded-[28px] border bg-card shadow-sm transition-colors dark:bg-[#241c1f]",
                    pipeline.borderClass,
                  )}
                >
                  <div className={cn("h-1 w-full bg-gradient-to-r", pipeline.accent)} />
                  <div className="space-y-6 p-5 md:p-6">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <span
                          className={cn(
                            "rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em]",
                            pipeline.badgeClass,
                          )}
                        >
                          Pipeline
                        </span>
                        <h3 className="mt-4 text-2xl font-semibold text-black dark:text-white">
                          {pipeline.name}
                        </h3>
                        <p className="mt-2 text-sm leading-6 text-muted-foreground">
                          {pipeline.summary}
                        </p>
                      </div>
                      <div className="rounded-2xl border border-gray-200 bg-background/80 p-3 dark:border-[#3D3D3D] dark:bg-black/10">
                        {pipeline.name === "LLM-Only" ? (
                          <BrainCircuit className="h-5 w-5 text-slate-500 dark:text-slate-200" />
                        ) : pipeline.name === "Basic RAG" ? (
                          <Database className="h-5 w-5 text-amber-600 dark:text-amber-200" />
                        ) : (
                          <GitBranchPlus className="h-5 w-5 text-orange-600 dark:text-orange-200" />
                        )}
                      </div>
                    </div>

                    <div className="rounded-[24px] border border-gray-200 bg-background/80 p-4 dark:border-[#3D3D3D] dark:bg-[#1d1719]">
                      <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
                        Final Answer
                      </p>
                      <p className="mt-3 text-sm leading-7 text-black dark:text-white">
                        {pipeline.answer}
                      </p>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2">
                      {pipeline.metrics.map((metric) => (
                        <div
                          key={`${pipeline.name}-${metric.label}`}
                          className="rounded-2xl border border-gray-200 bg-background/80 px-4 py-4 dark:border-[#3D3D3D] dark:bg-[#1d1719]"
                        >
                          <p className="text-sm text-muted-foreground">
                            {metric.label}
                          </p>
                          <p className="mt-2 text-lg font-semibold text-black dark:text-white">
                            {metric.value}
                          </p>
                          <p className="mt-2 text-sm leading-6 text-muted-foreground">
                            {metric.hint}
                          </p>
                        </div>
                      ))}
                    </div>

                    <div className="rounded-2xl border border-dashed border-gray-300 px-4 py-3 text-sm leading-6 text-muted-foreground dark:border-[#4a3b40]">
                      When the benchmark endpoints are wired, this card will
                      populate from the same query execution used by the other
                      two pipelines so the comparison stays apples-to-apples.
                    </div>
                  </div>
                </article>
              ))}
            </section>
          </div>
        </div>
      </main>
    </div>
  );
};

export default Comparison;
