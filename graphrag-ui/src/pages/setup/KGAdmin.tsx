import React, { useState, useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Database, Loader2, RefreshCw, Upload } from "lucide-react";
import { pauseIdleTimer, resumeIdleTimer } from "@/hooks/useIdleTimeout";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useConfirm } from "@/hooks/useConfirm";
import { useNavigate } from "react-router-dom";
import IngestGraph from "./IngestGraph";
import { readSiteSession, refreshSiteSession } from "@/lib/siteSession";

const KGAdmin = () => {
  const [confirm, confirmDialog, isConfirmDialogOpen] = useConfirm();
  const navigate = useNavigate();
  const [availableGraphs, setAvailableGraphs] = useState<string[]>([]);
  
  // Dialog states
  const [initializeDialogOpen, setInitializeDialogOpen] = useState(false);
  const [refreshDialogOpen, setRefreshDialogOpen] = useState(false);
  const [ingestDialogOpen, setIngestDialogOpen] = useState(false);

  // Reset states when dialogs close
  const handleInitializeDialogChange = (open: boolean) => {
    if (!open && isConfirmDialogOpen) {
      return;
    }
    setInitializeDialogOpen(open);
    if (!open) {
      setGraphName("");
      setStatusMessage("");
      setStatusType("");
    }
  };

  const handleRefreshDialogChange = (open: boolean) => {
    if (!open && isConfirmDialogOpen) {
      return;
    }
    setRefreshDialogOpen(open);
    if (!open) {
      setRefreshMessage("");
      setPollingActive(false);
    }
  };

  // Initialize state
  const [graphName, setGraphName] = useState("");
  const [isInitializing, setIsInitializing] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [statusType, setStatusType] = useState<"success" | "error" | "">("");

  // Refresh state
  const [refreshGraphName, setRefreshGraphName] = useState("");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState("");
  const [isRebuildRunning, setIsRebuildRunning] = useState(false);
  const isRebuildRunningRef = useRef(false);
  const [isCheckingStatus, setIsCheckingStatus] = useState(false);
  const [pollingActive, setPollingActive] = useState(false);

  // Load available graphs
  useEffect(() => {
    const syncGraphs = async () => {
      let store = readSiteSession();
      try {
        store = await refreshSiteSession();
      } catch {
        // fall back to cached session state
      }
      if (store.graphs && Array.isArray(store.graphs)) {
        setAvailableGraphs(store.graphs);
        if (store.graphs.length > 0 && !refreshGraphName) {
          setRefreshGraphName(store.graphs[0]);
        }
      } else {
        setAvailableGraphs([]);
      }
    };
    void syncGraphs();
  }, []);

  // Initialize Graph
  const handleInitializeGraph = async () => {
    if (!graphName.trim()) {
      setStatusMessage("Please enter a graph name");
      setStatusType("error");
      return;
    }

    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(graphName)) {
      setStatusMessage("Invalid graph name. Must start with a letter or underscore, followed by letters, digits, or underscores.");
      setStatusType("error");
      return;
    }

    setIsInitializing(true);
    setStatusMessage("Creating graph and initializing GraphRAG schema...");
    setStatusType("");

    try {
      const creds = sessionStorage.getItem("creds");
      if (!creds) {
        throw new Error("Not authenticated. Please login first.");
      }

      setStatusMessage("Step 1/2: Creating graph...");
      const createResponse = await fetch(`/ui/${graphName}/create_graph`, {
        method: "POST",
        headers: { Authorization: `Basic ${creds}` },
      });

      const createData = await createResponse.json();

      if (!createResponse.ok) {
        const detail = createData.detail;
        const msg = typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((d: any) => d.msg || JSON.stringify(d)).join("; ")
            : createData.message || `Failed to create graph: ${createResponse.statusText}`;
        throw new Error(msg);
      }

      if (createData.status !== "success") {
        if (createData.message && createData.message.includes("already exists")) {
          const shouldInitialize = await confirm(
            `Graph "${graphName}" already exists. Do you want to initialize it with GraphRAG schema?`
          );
          if (!shouldInitialize) {
            setStatusMessage("Operation cancelled by user.");
            setStatusType("error");
            setIsInitializing(false);
            return;
          }
        } else {
          throw new Error(
            createData.message || `Failed to create graph: ${createData.details}`
          );
        }
      }

      setStatusMessage("Step 2/2: Initializing GraphRAG schema...");
      const initResponse = await fetch(`/ui/${graphName}/initialize_graph`, {
        method: "POST",
        headers: { Authorization: `Basic ${creds}` },
      });

      const initData = await initResponse.json();

      if (!initResponse.ok) {
        throw new Error(
          initData.detail || `Failed to initialize graph: ${initResponse.statusText}`
        );
      }

      if (initData.status !== "success") {
        setStatusMessage(
          initData.message || `Failed to initialize graph: ${initData.details}`
        );
        setStatusType("error");
        setIsInitializing(false);
        return;
      }

      setStatusMessage(
        `✅ Graph "${graphName}" created and initialized successfully! You can now close this dialog.`
      );
      setStatusType("success");

      const newGraph = graphName;
      setAvailableGraphs(prev => {
        if (!prev.includes(newGraph)) {
          const updated = [...prev, newGraph];
          const store = JSON.parse(sessionStorage.getItem("site") || "{}");
          store.graphs = updated;
          sessionStorage.setItem("site", JSON.stringify(store));
          return updated;
        }
        return prev;
      });

      setRefreshGraphName(graphName);
      setGraphName("");
    } catch (error: any) {
      console.error("Error creating graph:", error);
      setStatusMessage(`❌ Error: ${error.message}`);
      setStatusType("error");
    } finally {
      setIsInitializing(false);
    }
  };

  // Check rebuild status
  const checkRebuildStatus = async (
    graphName: string,
    showLoadingMessage: boolean = false
  ) => {
    if (!graphName) return;

    setIsCheckingStatus(true);
    if (showLoadingMessage) {
      setRefreshMessage("Checking rebuild status...");
    }

    try {
      const creds = sessionStorage.getItem("creds");
      const statusResponse = await fetch(`/ui/${graphName}/rebuild_status`, {
        method: "GET",
        headers: { Authorization: `Basic ${creds}` },
      });

      if (statusResponse.ok) {
        const statusData = await statusResponse.json();
        const wasRunning = isRebuildRunningRef.current;
        const isCurrentlyRunning = statusData.is_running || false;

        setIsRebuildRunning(isCurrentlyRunning);
        isRebuildRunningRef.current = isCurrentlyRunning;

        if (isCurrentlyRunning) {
          setPollingActive(true);
          const startTime = statusData.started_at
            ? new Date(statusData.started_at * 1000).toLocaleString()
            : "unknown time";
          setRefreshMessage(
            `⚠️ A rebuild is already in progress for "${graphName}" (started at ${startTime}). Please wait for it to complete.`
          );
        } else if (wasRunning && statusData.status === "completed") {
          setRefreshMessage(`✅ Rebuild completed successfully for "${graphName}".`);
          setPollingActive(false);
        } else if (statusData.status === "failed") {
          setRefreshMessage(`❌ Previous rebuild failed: ${statusData.error || "Unknown error"}`);
          setPollingActive(false);
        } else if (statusData.status === "error") {
          setRefreshMessage(`❌ Failed to check rebuild status: ${statusData.error || "Unknown error"}`);
          setPollingActive(false);
        } else if (statusData.status === "unknown") {
          setRefreshMessage(`⚠️ ECC service returned unknown status. It may be unavailable.`);
          setPollingActive(false);
        } else {
          setRefreshMessage("");
        }
      } else {
        setRefreshMessage(`❌ Failed to check rebuild status (HTTP ${statusResponse.status}).`);
      }
    } catch (error: any) {
      console.error("Error checking rebuild status:", error);
      if (showLoadingMessage) {
        setRefreshMessage(`❌ Unable to reach ECC service: ${error.message || "Connection failed"}`);
      }
    } finally {
      setIsCheckingStatus(false);
    }
  };

  // Refresh Graph
  const handleRefreshGraph = async () => {
    if (!refreshGraphName) {
      setRefreshMessage("Please select a graph");
      return;
    }

    if (isRebuildRunning) {
      setRefreshMessage(
        `⚠️ A rebuild is already in progress. Please wait for it to complete.`
      );
      return;
    }

    setIsRefreshing(true);

    const shouldRefresh = await confirm(
      `Are you sure you want to refresh the knowledge graph "${refreshGraphName}"? This will rebuild the graph content.`
    );
    if (!shouldRefresh) {
      setRefreshMessage("Operation cancelled by user.");
      setIsRefreshing(false);
      return;
    }

    setRefreshMessage("Verifying rebuild status...");

    try {
      const creds = sessionStorage.getItem("creds");

      // Final status check to prevent race conditions
      const statusCheckResponse = await fetch(`/ui/${refreshGraphName}/rebuild_status`, {
        method: "GET",
        headers: { Authorization: `Basic ${creds}` },
      });

      if (statusCheckResponse.ok) {
        const statusData = await statusCheckResponse.json();
        if (statusData.is_running) {
          setRefreshMessage(`⚠️ A rebuild is already in progress for "${refreshGraphName}". Please wait for it to complete.`);
          setIsRebuildRunning(true);
          isRebuildRunningRef.current = true;
          setIsRefreshing(false);
          return;
        }
      }

      setRefreshMessage("Submitting rebuild request...");

      const response = await fetch(`/ui/${refreshGraphName}/rebuild_graph`, {
        method: "POST",
        headers: { Authorization: `Basic ${creds}` },
      });

      if (!response.ok) {
        const errorData = await response.json();
        if (response.status === 409) {
          setRefreshMessage(`⚠️ ${errorData.detail || errorData.message}`);
          setIsRefreshing(false);
          return;
        }
        throw new Error(
          errorData.detail || `Failed to refresh graph: ${response.statusText}`
        );
      }

      const data = await response.json();
      console.log("Refresh response:", data);

      setRefreshMessage(
        `✅ Refresh submitted successfully! The knowledge graph "${refreshGraphName}" is being rebuilt.`
      );
      setIsRebuildRunning(true);
      isRebuildRunningRef.current = true;
      setPollingActive(true);
    } catch (error: any) {
      console.error("Error refreshing graph:", error);
      setRefreshMessage(`❌ Error: ${error.message}`);
    } finally {
      setIsRefreshing(false);
    }
  };

  // Initial status check when dialog opens
  useEffect(() => {
    if (refreshDialogOpen && refreshGraphName) {
      checkRebuildStatus(refreshGraphName, true);
    }
  }, [refreshDialogOpen, refreshGraphName]);

  // Poll status only while a rebuild is actively running
  useEffect(() => {
    if (!pollingActive || !refreshDialogOpen || !refreshGraphName) return;

    pauseIdleTimer();
    const intervalId = setInterval(() => {
      checkRebuildStatus(refreshGraphName, false);
    }, 5000);

    return () => {
      clearInterval(intervalId);
      resumeIdleTimer();
    };
  }, [pollingActive, refreshDialogOpen, refreshGraphName]);

  return (
    <div className="p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-black dark:text-white mb-2">
            Knowledge Graph Setup
          </h1>
          <p className="text-sm text-gray-600 dark:text-[#D9D9D9]">
            Configure and manage your knowledge graphs
          </p>
        </div>

        {/* Card Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Initialize Card */}
          <div className="border border-gray-300 dark:border-[#3D3D3D] rounded-lg p-6 bg-white dark:bg-shadeA flex flex-col h-full">
            <div className="mb-4">
              <div className="w-12 h-12 rounded-full bg-tigerOrange/10 flex items-center justify-center mb-4">
                <Database className="h-6 w-6 text-tigerOrange" />
              </div>
              <h2 className="text-lg font-semibold mb-2 text-black dark:text-white">
                Initialize Knowledge Graph
              </h2>
              <p className="text-sm text-gray-600 dark:text-[#D9D9D9] mb-4">
                Create the knowledge graph schema and queries for future document ingestion.
              </p>
            </div>
            <div className="mt-auto pt-4 border-t border-gray-300 dark:border-[#3D3D3D]">
              <Button
                onClick={() => setInitializeDialogOpen(true)}
                className="gradient w-full text-white"
              >
                <Database className="h-4 w-4 mr-2" />
                Initialize Graph
              </Button>
            </div>
          </div>

          {/* Ingest Card */}
          <div className="border border-gray-300 dark:border-[#3D3D3D] rounded-lg p-6 bg-white dark:bg-shadeA flex flex-col h-full">
            <div className="mb-4">
              <div className="w-12 h-12 rounded-full bg-tigerOrange/10 flex items-center justify-center mb-4">
                <Upload className="h-6 w-6 text-tigerOrange" />
              </div>
              <h2 className="text-lg font-semibold mb-2 text-black dark:text-white">
                Ingest to Knowledge Graph
              </h2>
              <p className="text-sm text-gray-600 dark:text-[#D9D9D9] mb-4">
                Upload and ingest documents into your knowledge graph for future content processing.
              </p>
            </div>
            <div className="mt-auto pt-4 border-t border-gray-300 dark:border-[#3D3D3D]">
              <Button
                onClick={() => setIngestDialogOpen(true)}
                className="gradient w-full text-white"
              >
                <Upload className="h-4 w-4 mr-2" />
                Ingest Document
              </Button>
            </div>
          </div>

          {/* Refresh Card */}
          <div className="border border-gray-300 dark:border-[#3D3D3D] rounded-lg p-6 bg-white dark:bg-shadeA flex flex-col h-full">
            <div className="mb-4">
              <div className="w-12 h-12 rounded-full bg-tigerOrange/10 flex items-center justify-center mb-4">
                <RefreshCw className="h-6 w-6 text-tigerOrange" />
              </div>
              <h2 className="text-lg font-semibold mb-2 text-black dark:text-white">
                Refresh Knowledge Graph
              </h2>
              <p className="text-sm text-gray-600 dark:text-[#D9D9D9] mb-4">
                Process new documents in your knowledge graph to refresh its content.
              </p>
            </div>
            <div className="mt-auto pt-4 border-t border-gray-300 dark:border-[#3D3D3D]">
              <Button
                onClick={() => setRefreshDialogOpen(true)}
                className="gradient w-full text-white"
              >
                <RefreshCw className="h-4 w-4 mr-2" />
                Refresh Graph
              </Button>
            </div>
          </div>
        </div>

        {/* Initialize Dialog */}
        <Dialog open={initializeDialogOpen} onOpenChange={handleInitializeDialogChange}>
          <DialogContent
            className="sm:max-w-[500px] bg-white dark:bg-background border-gray-300 dark:border-[#3D3D3D]"
            onInteractOutside={(e) => e.preventDefault()}
          >
            <DialogHeader>
              <DialogTitle className="text-black dark:text-white">Initialize Knowledge Graph</DialogTitle>
              <DialogDescription className="text-gray-600 dark:text-[#D9D9D9]">
                Enter the name of your knowledge graph. The system will create it if necessary and initialize it with the GraphRAG schema.
              </DialogDescription>
            </DialogHeader>

            <div className="py-4">
              <div className="mb-4">
                <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                  Knowledge Graph Name
                </label>
                <Input
                  placeholder="e.g., MyKnowledgeGraph"
                  value={graphName}
                  onChange={(e) => setGraphName(e.target.value)}
                  disabled={isInitializing}
                  className="dark:border-[#3D3D3D] dark:bg-shadeA"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !isInitializing) {
                      handleInitializeGraph();
                    }
                  }}
                />
              </div>

              {statusMessage && (
                <div
                  className={`p-3 rounded-lg text-sm ${
                    statusType === "success"
                      ? "bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300"
                      : statusType === "error"
                      ? "bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300"
                      : "bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300"
                  }`}
                >
                  {statusMessage}
                </div>
              )}
            </div>

            <DialogFooter>
              {statusType === "success" ? (
                <Button
                  className="gradient text-white w-full"
                  onClick={() => {
                    setInitializeDialogOpen(false);
                    setGraphName("");
                    setStatusMessage("");
                    setStatusType("");
                  }}
                >
                  Done
                </Button>
              ) : (
                <>
                  <Button
                    variant="outline"
                    onClick={() => handleInitializeDialogChange(false)}
                    disabled={isInitializing}
                    className="dark:border-[#3D3D3D]"
                  >
                    Cancel
                  </Button>
                  <Button
                    onClick={handleInitializeGraph}
                    disabled={isInitializing || !graphName.trim()}
                    className="gradient text-white"
                  >
                    {isInitializing ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        Creating...
                      </>
                    ) : (
                      <>
                        <Database className="h-4 w-4 mr-2" />
                        Create & Initialize
                      </>
                    )}
                  </Button>
                </>
              )}
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* Ingest Dialog */}
        <Dialog
          open={ingestDialogOpen}
          onOpenChange={(open) => {
            if (!open && isConfirmDialogOpen) {
              return;
            }
            setIngestDialogOpen(open);
          }}
        >
          <DialogContent
            className="sm:max-w-[700px] bg-white dark:bg-background border-gray-300 dark:border-[#3D3D3D] max-h-[80vh] overflow-y-auto"
            onInteractOutside={(e) => e.preventDefault()}
          >
            <DialogHeader>
              <DialogTitle className="text-black dark:text-white">Document Ingestion for Knowledge Graph</DialogTitle>
              <DialogDescription className="text-gray-600 dark:text-[#D9D9D9]">
                Upload files locally, download from cloud storage, or configure Amazon Bedrock Data Automation for document ingestion
              </DialogDescription>
            </DialogHeader>
            <IngestGraph isModal={true} />
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setIngestDialogOpen(false)}
                className="dark:border-[#3D3D3D]"
              >
                Close
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* Refresh Dialog */}
        <Dialog open={refreshDialogOpen} onOpenChange={handleRefreshDialogChange}>
          <DialogContent
            className="sm:max-w-[500px] bg-white dark:bg-background border-gray-300 dark:border-[#3D3D3D]"
            onInteractOutside={(e) => e.preventDefault()}
          >
            <DialogHeader>
              <DialogTitle className="text-black dark:text-white">Refresh Knowledge Graph</DialogTitle>
              <DialogDescription className="text-gray-600 dark:text-[#D9D9D9]">
                Rebuild the graph content and rerun community detection for your knowledge graph
              </DialogDescription>
            </DialogHeader>

            <div className="py-4 space-y-4">
              <div>
                <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                  Select Graph to Refresh
                </label>
                <Select
                  value={refreshGraphName}
                  onValueChange={setRefreshGraphName}
                  disabled={isRefreshing || isRebuildRunning || isCheckingStatus}
                >
                  <SelectTrigger
                    className="dark:border-[#3D3D3D] dark:bg-shadeA"
                    disabled={isRefreshing || isRebuildRunning || isCheckingStatus}
                  >
                    <SelectValue placeholder="Select a graph" />
                  </SelectTrigger>
                  <SelectContent>
                    {availableGraphs.length > 0 ? (
                      availableGraphs.map((graph) => (
                        <SelectItem key={graph} value={graph}>
                          {graph}
                        </SelectItem>
                      ))
                    ) : (
                      <SelectItem value="no-graphs" disabled>
                        No graphs available
                      </SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>

              <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4">
                <p className="text-sm text-yellow-800 dark:text-yellow-200 font-medium">
                  ⚠️ Warning
                </p>
                <p className="text-sm text-yellow-700 dark:text-yellow-300 mt-1">
                  This operation will process new documents and rerun community detection that will interrupt related queries.
                  Please confirm to proceed.
                </p>
              </div>

              {refreshMessage && (
                <div className={`p-3 rounded-lg text-sm ${
                  refreshMessage.includes("✅")
                    ? "bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300"
                    : refreshMessage.includes("❌")
                    ? "bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300"
                    : "bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300"
                }`}>
                  {refreshMessage}
                </div>
              )}
            </div>

            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => handleRefreshDialogChange(false)}
                disabled={isRefreshing}
                className="dark:border-[#3D3D3D]"
              >
                Close
              </Button>
              <Button
                onClick={handleRefreshGraph}
                disabled={isRefreshing || !refreshGraphName || isRebuildRunning || isCheckingStatus}
                className="gradient text-white"
              >
                {isRefreshing ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Submitting...
                  </>
                ) : isRebuildRunning ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Rebuild In Progress...
                  </>
                ) : isCheckingStatus ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Checking Status...
                  </>
                ) : (
                  <>
                    <RefreshCw className="h-4 w-4 mr-2" />
                    Confirm & Refresh
                  </>
                )}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
      {confirmDialog}
    </div>
  );
};

export default KGAdmin;
