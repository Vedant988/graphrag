import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  AlertCircle,
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  Clock3,
  Database,
  Gauge,
  GitBranchPlus,
  Layers3,
  Loader2,
  Sparkles,
  Wallet,
} from "lucide-react";
import { MdKeyboardArrowDown } from "react-icons/md";
import { RxHamburgerMenu } from "react-icons/rx";

import SideMenu from "@/components/SideMenu";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { parseApiResponse } from "@/lib/http";
import { readSiteSession, refreshSiteSession } from "@/lib/siteSession";

const defaultQuestion =
  "Based entirely on the first 10 pages, trace the exact lineage and mentorship connections between the author of the Mahabharata and the warrior who was left lying on a bed of arrows. How are they connected?";

const benchmarkPreset = {
  id: "vyasa_bhishma_lineage",
  favoredPipeline: "GraphRAG favored multi-hop benchmark",
  category: "Lineage and mentorship benchmark",
  diagnosis:
    "This question usually rewards graph-grounded retrieval because the answer depends on multiple linked facts rather than one semantically similar chunk.",
};

type ComparisonUsage = {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost: number;
  calls: number;
};

type ComparisonLatencyStage = {
  key: string;
  label: string;
  seconds: number;
  detail: string;
  metadata?: Record<string, string | number | boolean | null>;
};

type ComparisonLatencyBreakdown = {
  summary?: string | null;
  stages: ComparisonLatencyStage[];
  accounted_seconds: number;
  total_seconds: number;
};

type ComparisonPipelineResult = {
  pipeline: string;
  status: string;
  answer: string;
  latency_seconds: number;
  usage: ComparisonUsage;
  error?: string | null;
  latency_breakdown?: ComparisonLatencyBreakdown;
  profile?: Record<string, unknown> | null;
};

type ComparisonResponse = {
  graphname: string;
  question: string;
  pipelines: ComparisonPipelineResult[];
};

const pipelineCards = [
  {
    name: "LLM-Only",
    accent: "from-slate-500/30 to-slate-700/10",
    badgeClass:
      "border-slate-500/30 bg-slate-500/10 text-slate-700 dark:text-slate-200",
    borderClass: "border-slate-300/80 dark:border-slate-700/70",
    summary: "Pure model response with no retrieval or graph evidence.",
    emptyState:
      "Run the benchmark to compare the ungrounded baseline against the retrieval pipelines.",
  },
  {
    name: "Basic RAG",
    accent: "from-amber-400/25 to-orange-500/10",
    badgeClass:
      "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-200",
    borderClass: "border-amber-300/70 dark:border-amber-900/60",
    summary: "Vector retrieval plus LLM synthesis over semantically similar chunks.",
    emptyState:
      "Run the benchmark to inspect the similarity-based baseline side by side with GraphRAG.",
  },
  {
    name: "GraphRAG",
    accent: "from-orange-500/30 to-emerald-500/10",
    badgeClass:
      "border-orange-500/40 bg-orange-500/10 text-orange-700 dark:text-orange-200",
    borderClass: "border-orange-300/80 dark:border-orange-800/70",
    summary: "Graph-aware retrieval, evidence ranking, and relationship-grounded synthesis.",
    emptyState:
      "Run the benchmark to see the graph-grounded answer and stage-level timing profile.",
  },
];

const formatTokens = (value?: number) =>
  typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString()
    : "--";

const formatLatency = (value?: number) =>
  typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(2)}s` : "--";

const formatCost = (value?: number) =>
  typeof value === "number" && Number.isFinite(value) ? `$${value.toFixed(4)}` : "--";

const formatPercent = (value: number) =>
  `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;

const formatMetadataValue = (value: string | number | boolean | null) => {
  if (typeof value === "boolean") {
    return value ? "yes" : "no";
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? `${value}` : value.toFixed(2);
  }
  return value ?? "--";
};

const normalizePipelineName = (value: string) => value.toLowerCase().replace(/\s+/g, "_");

const getDominantStage = (stages: ComparisonLatencyStage[]) =>
  [...stages].sort((left, right) => right.seconds - left.seconds)[0];

const Comparison = () => {
  const [showSidebar, setShowSidebar] = useState(true);
  const [store, setStore] = useState<any>();
  const [currentDate, setCurrentDate] = useState("");
  const [query, setQuery] = useState(defaultQuestion);
  const [submittedQuery, setSubmittedQuery] = useState(defaultQuestion);
  const [benchmarkData, setBenchmarkData] = useState<ComparisonResponse | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [selectedGraph, setSelectedGraph] = useState(
    typeof window !== "undefined"
      ? sessionStorage.getItem("selectedGraph") || "gemini_1_0"
      : "gemini_1_0",
  );
  const [ragPattern, setRagPattern] = useState(
    typeof window !== "undefined"
      ? sessionStorage.getItem("ragPattern") || "Auto Router"
      : "Auto Router",
  );
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const syncStore = async () => {
      try {
        const site = await refreshSiteSession();
        setStore(site);
        setSelectedGraph(sessionStorage.getItem("selectedGraph") || "gemini_1_0");
      } catch {
        const site = readSiteSession();
        setStore(site);
        setSelectedGraph(sessionStorage.getItem("selectedGraph") || "gemini_1_0");
      }
    };

    void syncStore();

    if (!sessionStorage.getItem("ragPattern")) {
      setRagPattern("Auto Router");
      sessionStorage.setItem("ragPattern", "Auto Router");
    }

    const date = new Date();
    const options: Intl.DateTimeFormatOptions = {
      year: "numeric",
      month: "long",
      day: "numeric",
      weekday: "long",
    };
    setCurrentDate(date.toLocaleDateString("en-US", options));

    const handleFocus = () => {
      void syncStore();
      setRagPattern(sessionStorage.getItem("ragPattern") || "Auto Router");
    };

    window.addEventListener("focus", handleFocus);
    return () => window.removeEventListener("focus", handleFocus);
  }, []);

  useEffect(() => {
    const syncStore = async () => {
      try {
        const site = await refreshSiteSession();
        setStore(site);
      } catch {
        setStore(readSiteSession());
      }
      setSelectedGraph(sessionStorage.getItem("selectedGraph") || "gemini_1_0");
      setRagPattern(sessionStorage.getItem("ragPattern") || "Auto Router");
    };
    void syncStore();
  }, [location]);

  const handleSelectGraph = (value: string) => {
    setSelectedGraph(value);
    sessionStorage.setItem("selectedGraph", value);
    window.dispatchEvent(new Event("graphrag:selectedGraph"));
    navigate("/comparison");
  };

  const handleSelectRag = (value: string) => {
    setRagPattern(value);
    sessionStorage.setItem("ragPattern", value);
    navigate("/comparison");
  };

  const pipelineResults = Object.fromEntries(
    (benchmarkData?.pipelines || []).map((result) => [result.pipeline, result]),
  ) as Record<string, ComparisonPipelineResult>;

  const successfulPipelines = (benchmarkData?.pipelines || []).filter(
    (result) => result.status === "success",
  );
  const fastestPipeline = [...successfulPipelines].sort(
    (left, right) => left.latency_seconds - right.latency_seconds,
  )[0];
  const leanestPipeline = [...successfulPipelines].sort(
    (left, right) => left.usage.total_tokens - right.usage.total_tokens,
  )[0];
  const cheapestPipeline = [...successfulPipelines].sort(
    (left, right) => left.usage.cost - right.usage.cost,
  )[0];
  const graphRag = pipelineResults["GraphRAG"];
  const basicRag = pipelineResults["Basic RAG"];

  const graphVsBasicNarrative =
    graphRag?.status === "success" && basicRag?.status === "success"
      ? (() => {
          const tokenDelta =
            basicRag.usage.total_tokens > 0
              ? ((basicRag.usage.total_tokens - graphRag.usage.total_tokens) /
                  basicRag.usage.total_tokens) *
                100
              : 0;
          const latencyDelta =
            basicRag.latency_seconds > 0
              ? ((basicRag.latency_seconds - graphRag.latency_seconds) /
                  basicRag.latency_seconds) *
                100
              : 0;
          return `GraphRAG delivered ${formatPercent(tokenDelta)} token efficiency and ${formatPercent(latencyDelta)} latency delta versus Basic RAG on this run.`;
        })()
      : "Run one live benchmark to see whether GraphRAG earns its overhead with cleaner context and sharper retrieval.";

  const summaryCards = benchmarkData
    ? [
        {
          label: "Fastest lane",
          value: fastestPipeline?.pipeline || "--",
          subvalue: fastestPipeline ? formatLatency(fastestPipeline.latency_seconds) : "--",
          icon: Clock3,
        },
        {
          label: "Leanest context",
          value: leanestPipeline?.pipeline || "--",
          subvalue: leanestPipeline ? formatTokens(leanestPipeline.usage.total_tokens) : "--",
          icon: Layers3,
        },
        {
          label: "Lowest spend",
          value: cheapestPipeline?.pipeline || "--",
          subvalue: cheapestPipeline ? formatCost(cheapestPipeline.usage.cost) : "--",
          icon: Wallet,
        },
        {
          label: "Transparency",
          value: "Stage timing active",
          subvalue: "Retrieval, ranking, and synthesis are separated",
          icon: Gauge,
        },
      ]
    : [
        {
          label: "Fastest lane",
          value: "Pending run",
          subvalue: "No latency data yet",
          icon: Clock3,
        },
        {
          label: "Leanest context",
          value: "Pending run",
          subvalue: "No token data yet",
          icon: Layers3,
        },
        {
          label: "Lowest spend",
          value: "Pending run",
          subvalue: "No cost data yet",
          icon: Wallet,
        },
        {
          label: "Transparency",
          value: "Stage timing ready",
          subvalue: "Backend breakdown will appear after the first run",
          icon: Gauge,
        },
      ];

  const handleRunBenchmark = async () => {
    const nextQuery = query.trim() || defaultQuestion;
    const creds =
      typeof window !== "undefined" ? sessionStorage.getItem("creds") : null;

    if (!selectedGraph) {
      setRunError("Select a knowledge graph before running the comparison.");
      return;
    }

    if (!creds) {
      setRunError("Your session is missing credentials. Please log in again.");
      return;
    }

    setSubmittedQuery(nextQuery);
    setIsRunning(true);
    setRunError(null);

    try {
      const response = await fetch(`/ui/${selectedGraph}/comparison`, {
        method: "POST",
        headers: {
          Authorization: `Basic ${creds}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ question: nextQuery }),
      });

      const data = await parseApiResponse(response);
      if (!response.ok) {
        throw new Error(data.detail || "Benchmark execution failed.");
      }

      setBenchmarkData(data);
    } catch (error) {
      setBenchmarkData(null);
      setRunError(
        error instanceof Error
          ? error.message
          : "Benchmark execution failed.",
      );
    } finally {
      setIsRunning(false);
    }
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
          <div className="border-b border-gray-300 bg-white px-5 dark:border-[#3D3D3D] dark:bg-background">
            <div className="flex min-h-[70px] flex-wrap items-center gap-4">
              <div className="mr-4 text-sm">{currentDate}</div>

              <div className="mr-auto flex flex-wrap gap-4">
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="outline"
                      className="!h-[48px] flex items-center justify-end bg-white dark:bg-background"
                    >
                      <img src="/graph-icon.svg" alt="" className="mr-2" />
                      {ragPattern} <MdKeyboardArrowDown className="text-2xl" />
                    </Button>
                  </DropdownMenuTrigger>

                  <DropdownMenuContent className="w-56">
                    <DropdownMenuLabel>Select a GraphRAG Pattern</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuGroup>
                      {[
                        "Auto Router",
                        "Similarity Search",
                        "Contextual Search",
                        "Hybrid Search",
                        "Community Search",
                      ].map((pattern) => (
                        <DropdownMenuItem
                          key={pattern}
                          onSelect={() => handleSelectRag(pattern)}
                        >
                          <span>{pattern}</span>
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuGroup>
                  </DropdownMenuContent>
                </DropdownMenu>

                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="outline"
                      className="!h-[48px] flex items-center justify-end bg-white dark:bg-background"
                    >
                      <img src="/graph-icon.svg" alt="" className="mr-2" />
                      {selectedGraph || (
                        <span className="italic text-gray-400">No Knowledge Graph</span>
                      )}{" "}
                      <MdKeyboardArrowDown className="text-2xl" />
                    </Button>
                  </DropdownMenuTrigger>

                  <DropdownMenuContent className="w-56">
                    <DropdownMenuLabel>Select a KnowledgeGraph</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuGroup>
                      {store?.graphs?.length > 0 ? (
                        store.graphs.map((graph: string) => (
                          <DropdownMenuItem
                            key={graph}
                            onSelect={() => handleSelectGraph(graph)}
                          >
                            <span>{graph}</span>
                          </DropdownMenuItem>
                        ))
                      ) : (
                        <DropdownMenuItem disabled>
                          <span className="text-sm italic text-gray-400">
                            Please create a Knowledge Graph in Setup first
                          </span>
                        </DropdownMenuItem>
                      )}
                    </DropdownMenuGroup>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </div>
          </div>

          <div className="pointer-events-none absolute -left-12 top-16 h-44 w-44 rounded-full bg-orange-500/10 blur-3xl" />
          <div className="pointer-events-none absolute right-0 top-24 h-64 w-64 rounded-full bg-amber-500/10 blur-3xl" />

          <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 pb-10 pt-16 md:px-8">
            <section className="rounded-[30px] border border-gray-200/80 bg-card/90 p-6 shadow-sm dark:border-[#3D3D3D] dark:bg-[#221b1d]/90 md:p-8">
              <div className="grid gap-8 xl:grid-cols-[1.5fr_0.95fr]">
                <div className="space-y-5">
                  <div className="flex flex-wrap gap-3 text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                    <span className="rounded-full border border-orange-500/30 bg-orange-500/10 px-3 py-1 font-semibold text-orange-700 dark:text-orange-200">
                      Comparison Dashboard
                    </span>
                    <span className="rounded-full border border-gray-300 px-3 py-1 font-semibold dark:border-[#3D3D3D]">
                      Graph: {selectedGraph}
                    </span>
                  </div>

                  <div className="space-y-3">
                    <h1 className="Urbane-Medium max-w-4xl text-4xl leading-tight text-black dark:text-white md:text-5xl">
                      Three pipelines. One question. A cleaner story.
                    </h1>
                    <p className="max-w-3xl text-base leading-7 text-muted-foreground md:text-lg">
                      This view now reads like an executive review instead of a dump.
                      Run the same prompt through LLM-Only, Basic RAG, and GraphRAG,
                      then inspect where time and tokens were actually spent.
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
                      <CheckCircle2 className="h-4 w-4 text-orange-500" />
                      Stage-level latency breakdown is live.
                    </div>
                  </div>
                </div>

                <div className="rounded-[26px] border border-gray-200/80 bg-background/70 p-5 dark:border-[#3D3D3D] dark:bg-black/10">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                        Benchmark Brief
                      </p>
                      <h2 className="mt-2 text-2xl font-semibold text-black dark:text-white">
                        Premium surface, less noise.
                      </h2>
                    </div>
                    <div className="rounded-2xl border border-orange-500/30 bg-orange-500/10 p-3">
                      <Gauge className="h-5 w-5 text-orange-600 dark:text-orange-200" />
                    </div>
                  </div>

                  <div className="mt-5 space-y-4">
                    <div className="rounded-2xl border border-gray-200 bg-card px-4 py-4 dark:border-[#3D3D3D] dark:bg-[#2a2024]">
                      <p className="text-sm text-muted-foreground">Selected graph</p>
                      <p className="mt-2 text-lg font-semibold text-black dark:text-white">
                        {selectedGraph}
                      </p>
                    </div>

                    <div className="rounded-2xl border border-gray-200 bg-card px-4 py-4 dark:border-[#3D3D3D] dark:bg-[#2a2024]">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-700 dark:text-amber-200">
                          {benchmarkPreset.id}
                        </span>
                        <span className="rounded-full border border-gray-300 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] dark:border-[#3D3D3D]">
                          {benchmarkPreset.category}
                        </span>
                      </div>
                      <p className="mt-3 text-sm leading-6 text-muted-foreground">
                        {benchmarkPreset.diagnosis}
                      </p>
                    </div>

                    <div className="rounded-2xl border border-orange-500/20 bg-orange-500/[0.06] px-4 py-4">
                      <p className="text-sm leading-6 text-muted-foreground">
                        {graphVsBasicNarrative}
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </section>

            <section className="grid gap-4 lg:grid-cols-4">
              {summaryCards.map((card) => {
                const Icon = card.icon;
                return (
                  <div
                    key={card.label}
                    className="rounded-[24px] border border-gray-200 bg-card p-5 shadow-sm dark:border-[#3D3D3D] dark:bg-[#241c1f]"
                  >
                    <div className="flex items-center justify-between gap-4">
                      <p className="text-sm text-muted-foreground">{card.label}</p>
                      <div className="rounded-2xl border border-orange-500/20 bg-orange-500/10 p-2.5">
                        <Icon className="h-4 w-4 text-orange-600 dark:text-orange-200" />
                      </div>
                    </div>
                    <p className="mt-4 text-xl font-semibold text-black dark:text-white">
                      {card.value}
                    </p>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      {card.subvalue}
                    </p>
                  </div>
                );
              })}
            </section>

            <section className="rounded-[28px] border border-gray-200 bg-card p-5 shadow-sm dark:border-[#3D3D3D] dark:bg-[#241c1f] md:p-6">
              <div className="grid gap-6 xl:grid-cols-[1.4fr_0.9fr]">
                <div className="space-y-4">
                  <div>
                    <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                      Live Comparison
                    </p>
                    <h2 className="mt-2 text-3xl font-semibold text-black dark:text-white">
                      One run, with the latency story exposed.
                    </h2>
                    <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
                      The comparison endpoint now separates retrieval, ranking, and synthesis so the total latency is not a black box anymore.
                    </p>
                  </div>

                  <div className="grid gap-3 xl:grid-cols-[1fr_auto]">
                    <Input
                      className="h-14 rounded-2xl border-gray-300 bg-background px-5 text-base dark:border-[#3D3D3D] dark:bg-[#1c1518]"
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" && !isRunning) {
                          handleRunBenchmark();
                        }
                      }}
                      placeholder="Ask one benchmark question for all three pipelines..."
                    />
                    <Button
                      className="gradient h-14 rounded-2xl border-0 px-6 text-white hover:opacity-95"
                      type="button"
                      onClick={handleRunBenchmark}
                      disabled={isRunning}
                    >
                      {isRunning ? "Running Benchmark" : "Run Live Benchmark"}
                      {isRunning ? (
                        <Loader2 className="ml-2 h-4 w-4 animate-spin" />
                      ) : (
                        <Sparkles className="ml-2 h-4 w-4" />
                      )}
                    </Button>
                  </div>

                  <div className="rounded-2xl border border-dashed border-orange-500/40 bg-orange-500/[0.06] px-4 py-3 text-sm leading-6 text-muted-foreground">
                    Current query:
                    <span className="ml-2 font-medium text-black dark:text-white">
                      {submittedQuery}
                    </span>
                  </div>

                  {runError ? (
                    <div className="flex items-start gap-3 rounded-2xl border border-red-300/60 bg-red-500/[0.06] px-4 py-3 text-sm leading-6 text-red-700 dark:border-red-900/70 dark:text-red-200">
                      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>{runError}</span>
                    </div>
                  ) : null}
                </div>

                <div className="rounded-[24px] border border-gray-200/80 bg-background/70 p-5 dark:border-[#3D3D3D] dark:bg-black/10">
                  <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                    What changed
                  </p>
                  <div className="mt-4 space-y-3">
                    <div className="rounded-2xl border border-gray-200 bg-card px-4 py-4 dark:border-[#3D3D3D] dark:bg-[#2a2024]">
                      <p className="text-sm font-medium text-black dark:text-white">
                        Quieter visual hierarchy
                      </p>
                      <p className="mt-2 text-sm leading-6 text-muted-foreground">
                        Long explainer text is now compressed into tighter summary blocks and opt-in disclosures.
                      </p>
                    </div>
                    <div className="rounded-2xl border border-gray-200 bg-card px-4 py-4 dark:border-[#3D3D3D] dark:bg-[#2a2024]">
                      <p className="text-sm font-medium text-black dark:text-white">
                        Explainable latency
                      </p>
                      <p className="mt-2 text-sm leading-6 text-muted-foreground">
                        Every pipeline now reports stage timings so you can see whether retrieval, ranking, or synthesis dominated the run.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </section>

            <section className="grid gap-5 2xl:grid-cols-3">
              {pipelineCards.map((pipeline) => {
                const result = pipelineResults[pipeline.name];
                const isSuccess = result?.status === "success";
                const stages = result?.latency_breakdown?.stages || [];
                const dominantStage = getDominantStage(stages);
                const dominantStageSeconds = Math.max(
                  ...stages.map((stage) => stage.seconds),
                  0.001,
                );
                const answer = result?.error
                  ? result.error
                  : result?.answer || pipeline.emptyState;

                return (
                  <article
                    key={pipeline.name}
                    className={cn(
                      "overflow-hidden rounded-[28px] border bg-card shadow-sm transition-colors dark:bg-[#241c1f]",
                      pipeline.borderClass,
                    )}
                  >
                    <div className={cn("h-1 w-full bg-gradient-to-r", pipeline.accent)} />
                    <div className="space-y-5 p-5 md:p-6">
                      <div className="flex items-start justify-between gap-4">
                        <div className="space-y-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <span
                              className={cn(
                                "rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em]",
                                pipeline.badgeClass,
                              )}
                            >
                              {pipeline.name}
                            </span>
                            <span className="rounded-full border border-gray-300 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] dark:border-[#3D3D3D]">
                              {isSuccess ? "Completed" : result?.error ? "Failed" : "Standby"}
                            </span>
                          </div>
                          <div>
                            <h3 className="text-2xl font-semibold text-black dark:text-white">
                              {pipeline.name}
                            </h3>
                            <p className="mt-2 text-sm leading-6 text-muted-foreground">
                              {pipeline.summary}
                            </p>
                          </div>
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

                      <div className="grid gap-3 sm:grid-cols-3">
                        <div className="rounded-2xl border border-gray-200 bg-background/80 px-4 py-4 dark:border-[#3D3D3D] dark:bg-[#1d1719]">
                          <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                            Tokens
                          </p>
                          <p className="mt-3 text-xl font-semibold text-black dark:text-white">
                            {formatTokens(result?.usage?.total_tokens)}
                          </p>
                        </div>
                        <div className="rounded-2xl border border-gray-200 bg-background/80 px-4 py-4 dark:border-[#3D3D3D] dark:bg-[#1d1719]">
                          <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                            Cost
                          </p>
                          <p className="mt-3 text-xl font-semibold text-black dark:text-white">
                            {formatCost(result?.usage?.cost)}
                          </p>
                        </div>
                        <div className="rounded-2xl border border-gray-200 bg-background/80 px-4 py-4 dark:border-[#3D3D3D] dark:bg-[#1d1719]">
                          <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                            Total latency
                          </p>
                          <p className="mt-3 text-xl font-semibold text-black dark:text-white">
                            {formatLatency(result?.latency_seconds)}
                          </p>
                        </div>
                      </div>

                      <details className="group rounded-[24px] border border-gray-200 bg-background/80 px-4 py-4 dark:border-[#3D3D3D] dark:bg-[#1d1719]">
                        <summary className="flex cursor-pointer list-none items-start justify-between gap-4">
                          <div className="min-w-0">
                            <div className="flex items-center gap-3">
                              <div className="rounded-2xl border border-orange-500/20 bg-orange-500/10 p-2.5">
                                <Clock3 className="h-4 w-4 text-orange-600 dark:text-orange-200" />
                              </div>
                              <div>
                                <p className="text-sm font-medium text-black dark:text-white">
                                  Latency Lens
                                </p>
                                <p className="text-xs leading-5 text-muted-foreground">
                                  {dominantStage
                                    ? `${dominantStage.label} dominated this run at ${formatLatency(dominantStage.seconds)}.`
                                    : "Open to review the timing breakdown for this pipeline."}
                                </p>
                              </div>
                            </div>
                            <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.15em] text-muted-foreground">
                              <span className="rounded-full border border-gray-300 px-3 py-1 dark:border-[#3D3D3D]">
                                total {formatLatency(result?.latency_breakdown?.total_seconds)}
                              </span>
                              <span className="rounded-full border border-gray-300 px-3 py-1 dark:border-[#3D3D3D]">
                                stages {stages.length}
                              </span>
                              <span className="rounded-full border border-gray-300 px-3 py-1 dark:border-[#3D3D3D]">
                                llm calls {result?.usage?.calls ?? 0}
                              </span>
                            </div>
                          </div>
                          <ChevronDown className="mt-1 h-4 w-4 shrink-0 transition-transform group-open:rotate-180 text-muted-foreground" />
                        </summary>

                        <div className="mt-4 border-t border-gray-200 pt-4 dark:border-[#3D3D3D]">
                          <p className="text-sm leading-6 text-muted-foreground">
                            {result?.latency_breakdown?.summary ||
                              "Stage timing appears here after the benchmark runs."}
                          </p>

                          <div className="mt-4 space-y-3">
                            {stages.length > 0 ? (
                              stages.map((stage) => (
                                <div key={`${pipeline.name}-${stage.key}`} className="space-y-2">
                                  <div className="flex items-center justify-between gap-4">
                                    <div className="min-w-0">
                                      <p className="text-sm font-medium text-black dark:text-white">
                                        {stage.label}
                                      </p>
                                      <p className="text-xs leading-5 text-muted-foreground">
                                        {stage.detail}
                                      </p>
                                    </div>
                                    <p className="shrink-0 text-sm font-semibold text-black dark:text-white">
                                      {formatLatency(stage.seconds)}
                                    </p>
                                  </div>
                                  <div className="h-2 overflow-hidden rounded-full bg-black/5 dark:bg-white/10">
                                    <div
                                      className={cn(
                                        "h-full rounded-full bg-gradient-to-r",
                                        pipeline.accent,
                                      )}
                                      style={{
                                        width: `${Math.max(
                                          12,
                                          (stage.seconds / dominantStageSeconds) * 100,
                                        )}%`,
                                      }}
                                    />
                                  </div>
                                  {stage.metadata &&
                                  Object.keys(stage.metadata).length > 0 ? (
                                    <div className="flex flex-wrap gap-2 text-[11px] uppercase tracking-[0.15em] text-muted-foreground">
                                      {Object.entries(stage.metadata).map(([key, value]) => (
                                        <span
                                          key={`${pipeline.name}-${stage.key}-${key}`}
                                          className="rounded-full border border-gray-300 px-2.5 py-1 dark:border-[#3D3D3D]"
                                        >
                                          {key.replace(/_/g, " ")} {formatMetadataValue(value)}
                                        </span>
                                      ))}
                                    </div>
                                  ) : null}
                                </div>
                              ))
                            ) : (
                              <div className="rounded-2xl border border-dashed border-gray-300 px-4 py-3 text-sm leading-6 text-muted-foreground dark:border-[#4a3b40]">
                                Run the benchmark to reveal how this pipeline spent its time.
                              </div>
                            )}
                          </div>

                          {result?.latency_breakdown?.total_seconds ? (
                            <div className="mt-4 flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.15em] text-muted-foreground">
                              <span className="rounded-full border border-gray-300 px-3 py-1 dark:border-[#3D3D3D]">
                                total {formatLatency(result.latency_breakdown.total_seconds)}
                              </span>
                              <span className="rounded-full border border-gray-300 px-3 py-1 dark:border-[#3D3D3D]">
                                accounted {formatLatency(result.latency_breakdown.accounted_seconds)}
                              </span>
                              <span className="rounded-full border border-gray-300 px-3 py-1 dark:border-[#3D3D3D]">
                                llm calls {result.usage.calls}
                              </span>
                            </div>
                          ) : null}
                        </div>
                      </details>

                      <details open className="group rounded-[24px] border border-gray-200 bg-background/80 px-4 py-4 dark:border-[#3D3D3D] dark:bg-[#1d1719]">
                        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-medium text-black dark:text-white">
                          Review answer
                          <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
                        </summary>
                        <p
                          className={cn(
                            "mt-4 text-sm leading-7",
                            result?.error
                              ? "text-red-700 dark:text-red-200"
                              : "text-black dark:text-white",
                          )}
                        >
                          {answer}
                        </p>
                      </details>

                      {result?.profile ? (
                        <details className="group rounded-[24px] border border-gray-200 bg-background/80 px-4 py-4 dark:border-[#3D3D3D] dark:bg-[#1d1719]">
                          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-medium text-black dark:text-white">
                            Review pipeline notes
                            <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
                          </summary>
                          <div className="mt-4 flex flex-wrap gap-2 text-[11px] uppercase tracking-[0.15em] text-muted-foreground">
                            {Object.entries(result.profile).map(([key, value]) => (
                              <span
                                key={`${normalizePipelineName(pipeline.name)}-${key}`}
                                className="rounded-full border border-gray-300 px-3 py-1 dark:border-[#3D3D3D]"
                              >
                                {key.replace(/_/g, " ")} {formatMetadataValue(value as string | number | boolean | null)}
                              </span>
                            ))}
                          </div>
                        </details>
                      ) : null}
                    </div>
                  </article>
                );
              })}
            </section>
          </div>
        </div>
      </main>
    </div>
  );
};

export default Comparison;
