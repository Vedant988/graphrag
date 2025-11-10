import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Database, Upload, RefreshCw, Loader2, Trash2, FolderUp, Cloud, ArrowLeft, CloudDownload } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const Setup = () => {
  const navigate = useNavigate();
  const [availableGraphs, setAvailableGraphs] = useState<string[]>([]);
  
  const [createGraphOpen, setCreateGraphOpen] = useState(false);
  const [graphName, setGraphName] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [statusType, setStatusType] = useState<"success" | "error" | "">("");

  // Data Ingest state
  const [ingestOpen, setIngestOpen] = useState(false);
  const [ingestGraphName, setIngestGraphName] = useState(""); // Graph to use for ingestion
  const [selectedFiles, setSelectedFiles] = useState<FileList | null>(null);
  const [uploadedFiles, setUploadedFiles] = useState<any[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState("");
  const [isIngesting, setIsIngesting] = useState(false);
  const [ingestMessage, setIngestMessage] = useState("");

  // Refresh state
  const [refreshOpen, setRefreshOpen] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState("");
  const [refreshGraphName, setRefreshGraphName] = useState("");
  
  // S3 state
  const [fileFormat, setFileFormat] = useState<"json" | "multi">("json");
  const [awsAccessKey, setAwsAccessKey] = useState("");
  const [awsSecretKey, setAwsSecretKey] = useState("");
  const [dataPath, setDataPath] = useState("");
  const [inputBucket, setInputBucket] = useState("");
  const [outputBucket, setOutputBucket] = useState("");
  const [regionName, setRegionName] = useState("");

  // Cloud Download state
  const [cloudProvider, setCloudProvider] = useState<"s3" | "gcs" | "azure">("s3");
  const [cloudAccessKey, setCloudAccessKey] = useState("");
  const [cloudSecretKey, setCloudSecretKey] = useState("");
  const [cloudBucket, setCloudBucket] = useState("");
  const [cloudRegion, setCloudRegion] = useState("");
  const [cloudPrefix, setCloudPrefix] = useState("");
  // GCS specific
  const [gcsProjectId, setGcsProjectId] = useState("");
  const [gcsCredentials, setGcsCredentials] = useState("");
  // Azure specific
  const [azureAccountName, setAzureAccountName] = useState("");
  const [azureAccountKey, setAzureAccountKey] = useState("");
  const [azureContainer, setAzureContainer] = useState("");
  // Cloud download files state
  const [downloadedFiles, setDownloadedFiles] = useState<any[]>([]);
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadMessage, setDownloadMessage] = useState("");

  // Fetch uploaded files
  const fetchUploadedFiles = async () => {
    if (!ingestGraphName) return;

    try {
      const creds = localStorage.getItem("creds");
      const response = await fetch(`/ui/${ingestGraphName}/uploads/list`, {
        headers: { Authorization: `Basic ${creds}` },
      });
      const data = await response.json();
      setUploadedFiles(data.files || []);
    } catch (error) {
      console.error("Error fetching files:", error);
    }
  };

  // Upload files
  const handleUploadFiles = async () => {
    if (!selectedFiles || selectedFiles.length === 0) {
      setUploadMessage("Please select files to upload");
      return;
    }

    if (!ingestGraphName) {
      setUploadMessage("Please enter a graph name");
      return;
    }

    setIsUploading(true);
    setUploadMessage("Uploading files...");

    try {
      const creds = localStorage.getItem("creds");
      const formData = new FormData();
      for (let i = 0; i < selectedFiles.length; i++) {
        formData.append("files", selectedFiles[i]);
      }

      const response = await fetch(`/ui/${ingestGraphName}/uploads?overwrite=true`, {
        method: "POST",
        headers: { Authorization: `Basic ${creds}` },
        body: formData,
      });

      const data = await response.json();
      if (data.status === "success") {
        setUploadMessage(`✅ ${data.message}`);
        setSelectedFiles(null);
        await fetchUploadedFiles();
      } else {
        setUploadMessage(`⚠️ ${data.message}`);
      }
    } catch (error: any) {
      setUploadMessage(`❌ Error: ${error.message}`);
    } finally {
      setIsUploading(false);
    }
  };

  // Delete a specific file
  const handleDeleteFile = async (filename: string) => {
    if (!ingestGraphName) return;

    try {
      const creds = localStorage.getItem("creds");
      const response = await fetch(
        `/ui/${ingestGraphName}/uploads?filename=${encodeURIComponent(filename)}`,
        {
          method: "DELETE",
          headers: { Authorization: `Basic ${creds}` },
        }
      );
      const data = await response.json();
      setUploadMessage(`✅ ${data.message}`);
      await fetchUploadedFiles();
    } catch (error: any) {
      setUploadMessage(`❌ Error: ${error.message}`);
    }
  };

  // Delete all files
  const handleDeleteAllFiles = async () => {
    if (!ingestGraphName) return;

    if (!confirm("Are you sure you want to delete all uploaded files?")) return;

    try {
      const creds = localStorage.getItem("creds");
      const response = await fetch(`/ui/${ingestGraphName}/uploads`, {
        method: "DELETE",
        headers: { Authorization: `Basic ${creds}` },
      });
      const data = await response.json();
      setUploadMessage(`✅ ${data.message}`);
      await fetchUploadedFiles();
    } catch (error: any) {
      setUploadMessage(`❌ Error: ${error.message}`);
    }
  };

  // Fetch downloaded files from cloud
  const fetchDownloadedFiles = async () => {
    if (!ingestGraphName) return;

    try {
      const creds = localStorage.getItem("creds");
      const response = await fetch(`/ui/${ingestGraphName}/cloud/list`, {
        headers: { Authorization: `Basic ${creds}` },
      });
      const data = await response.json();
      setDownloadedFiles(data.files || []);
    } catch (error) {
      console.error("Error fetching downloaded files:", error);
    }
  };

  // Handle cloud download
  const handleCloudDownload = async () => {
    if (!ingestGraphName) {
      setDownloadMessage("Please select a graph");
      return;
    }

    setIsDownloading(true);
    setDownloadMessage("Downloading files from cloud storage...");

    try {
      const creds = localStorage.getItem("creds");
      
      // Prepare request body based on provider
      let requestBody: any = { provider: cloudProvider };

      if (cloudProvider === "s3") {
        if (!cloudAccessKey || !cloudSecretKey || !cloudBucket || !cloudRegion) {
          setDownloadMessage("❌ Please fill in all S3 credentials");
          setIsDownloading(false);
          return;
        }
        requestBody = {
          ...requestBody,
          access_key: cloudAccessKey,
          secret_key: cloudSecretKey,
          bucket: cloudBucket,
          region: cloudRegion,
          prefix: cloudPrefix,
        };
      } else if (cloudProvider === "gcs") {
        if (!gcsProjectId || !gcsCredentials || !cloudBucket) {
          setDownloadMessage("❌ Please fill in all GCS credentials");
          setIsDownloading(false);
          return;
        }
        requestBody = {
          ...requestBody,
          project_id: gcsProjectId,
          gcs_credentials_json: gcsCredentials,
          bucket: cloudBucket,
          prefix: cloudPrefix,
        };
      } else if (cloudProvider === "azure") {
        if (!azureAccountName || !azureAccountKey || !azureContainer) {
          setDownloadMessage("❌ Please fill in all Azure credentials");
          setIsDownloading(false);
          return;
        }
        requestBody = {
          ...requestBody,
          account_name: azureAccountName,
          account_key: azureAccountKey,
          container: azureContainer,
          prefix: cloudPrefix,
        };
      }

      const response = await fetch(`/ui/${ingestGraphName}/cloud/download`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Basic ${creds}`,
        },
        body: JSON.stringify(requestBody),
      });

      const data = await response.json();
      if (data.status === "success") {
        setDownloadMessage(`✅ ${data.message}`);
        await fetchDownloadedFiles();
      } else if (data.status === "warning") {
        setDownloadMessage(`⚠️ ${data.message}`);
      } else {
        setDownloadMessage(`❌ ${data.message || "Download failed"}`);
      }
    } catch (error: any) {
      setDownloadMessage(`❌ Error: ${error.message}`);
    } finally {
      setIsDownloading(false);
    }
  };

  // Delete a specific downloaded file
  const handleDeleteDownloadedFile = async (filename: string) => {
    if (!ingestGraphName) return;

    try {
      const creds = localStorage.getItem("creds");
      const response = await fetch(
        `/ui/${ingestGraphName}/cloud/delete?filename=${encodeURIComponent(filename)}`,
        {
          method: "DELETE",
          headers: { Authorization: `Basic ${creds}` },
        }
      );
      const data = await response.json();
      setDownloadMessage(`✅ ${data.message}`);
      await fetchDownloadedFiles();
    } catch (error: any) {
      setDownloadMessage(`❌ Error: ${error.message}`);
    }
  };

  // Delete all downloaded files
  const handleDeleteAllDownloadedFiles = async () => {
    if (!ingestGraphName) return;

    if (!confirm("Are you sure you want to delete all downloaded files?")) return;

    try {
      const creds = localStorage.getItem("creds");
      const response = await fetch(`/ui/${ingestGraphName}/cloud/delete`, {
        method: "DELETE",
        headers: { Authorization: `Basic ${creds}` },
      });
      const data = await response.json();
      setDownloadMessage(`✅ ${data.message}`);
      await fetchDownloadedFiles();
    } catch (error: any) {
      setDownloadMessage(`❌ Error: ${error.message}`);
    }
  };

  // Ingest files into knowledge graph (uploaded or downloaded)
  const handleIngestData = async (sourceType: "uploaded" | "downloaded" = "uploaded") => {
    if (!ingestGraphName) {
      setIngestMessage("Please select a graph");
      return;
    }

    const folderPath = sourceType === "uploaded" 
      ? `uploads/${ingestGraphName}`
      : `downloaded_files_cloud/${ingestGraphName}`;

    setIsIngesting(true);
    setIngestMessage("Step 1/2: Creating ingest job...");

    try {
      const creds = localStorage.getItem("creds");

      // Step 1: Create ingest job
      const createIngestConfig = {
        data_source: "server",
        data_source_config: {
          folder_path: folderPath
        },
        loader_config: {},
        file_format: "multi"
      };

      const createResponse = await fetch(`/${ingestGraphName}/graphrag/create_ingest`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Basic ${creds}`,
        },
        body: JSON.stringify(createIngestConfig),
      });

      if (!createResponse.ok) {
        const errorData = await createResponse.json();
        throw new Error(errorData.detail || `Failed to create ingest job: ${createResponse.statusText}`);
      }

      const createData = await createResponse.json();
      console.log("Create ingest response:", createData);

      // Step 2: Run ingest
      setIngestMessage("Step 2/2: Running document ingest...");

      const loadingInfo = {
        load_job_id: createData.load_job_id,
        data_source_id: createData.data_source_id,
        file_path: createData.data_path || createData.file_path, // Handle both field names
      };

      const ingestResponse = await fetch(`/${ingestGraphName}/graphrag/ingest`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Basic ${creds}`,
        },
        body: JSON.stringify(loadingInfo),
      });

      if (!ingestResponse.ok) {
        const errorData = await ingestResponse.json();
        throw new Error(errorData.detail || `Failed to run ingest: ${ingestResponse.statusText}`);
      }

      const ingestData = await ingestResponse.json();
      console.log("Ingest response:", ingestData);

      setIngestMessage(`✅ Data ingested successfully! Processed documents from ${folderPath}/`);
    } catch (error: any) {
      console.error("Error ingesting data:", error);
      setIngestMessage(`❌ Error: ${error.message}`);
    } finally {
      setIsIngesting(false);
    }
  };

  // Handle refresh knowledge graph
  const handleRefreshGraph = async () => {
    if (!refreshGraphName) {
      setRefreshMessage("Please select a graph");
      return;
    }

    setIsRefreshing(true);
    setRefreshMessage("Rebuilding community...");

    try {
      const creds = localStorage.getItem("creds");
      const response = await fetch(`/${refreshGraphName}/graphrag/forceupdate`, {
        method: "GET",
        headers: {
          Authorization: `Basic ${creds}`,
        },
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `Failed to refresh graph: ${response.statusText}`);
      }

      const data = await response.json();
      console.log("Refresh response:", data);

      setRefreshMessage(`✅ Refresh submitted successfully! The knowledge graph "${refreshGraphName}" is being rebuilt.`);
    } catch (error: any) {
      console.error("Error refreshing graph:", error);
      setRefreshMessage(`❌ Error: ${error.message}`);
    } finally {
      setIsRefreshing(false);
    }
  };

  // Load available graphs from localStorage on mount
  useEffect(() => {
    const store = JSON.parse(localStorage.getItem("site") || "{}");
    if (store.graphs && Array.isArray(store.graphs)) {
      setAvailableGraphs(store.graphs);
      // Auto-select first graph if available
      if (store.graphs.length > 0 && !ingestGraphName) {
        setIngestGraphName(store.graphs[0]);
      }
      // Auto-select first graph for refresh as well
      if (store.graphs.length > 0 && !refreshGraphName) {
        setRefreshGraphName(store.graphs[0]);
      }
    }
  }, []);

  // Load files when ingest dialog opens or graph name changes
  useEffect(() => {
    if (ingestOpen && ingestGraphName) {
      fetchUploadedFiles();
      fetchDownloadedFiles();
    }
  }, [ingestOpen, ingestGraphName]);

  const handleCreateGraph = async () => {
    if (!graphName.trim()) {
      setStatusMessage("Please enter a graph name");
      setStatusType("error");
      return;
    }

    setIsCreating(true);
    setStatusMessage("Creating graph and initializing GraphRAG schema...");
    setStatusType("");

    try {
      // Get credentials from localStorage
      const creds = localStorage.getItem("creds");
      if (!creds) {
        throw new Error("Not authenticated. Please login first.");
      }

      // Step 1: Create the graph
      setStatusMessage("Step 1/2: Creating graph...");
      const createResponse = await fetch(`/${graphName}/graphrag/create_graph`, {
        method: "POST",
        headers: {
          Authorization: `Basic ${creds}`,
        },
      });

      const createData = await createResponse.json();

      if (!createResponse.ok) {
        throw new Error(createData.detail || createData.message || `Failed to create graph: ${createResponse.statusText}`);
      }

      if (createData.status === "error") {
        throw new Error(createData.message || "Failed to create graph");
      }

      // Step 2: Initialize the graph with GraphRAG schema
      setStatusMessage("Step 2/2: Initializing GraphRAG schema...");
      const initResponse = await fetch(`/${graphName}/graphrag/initialize`, {
        method: "POST",
        headers: {
          Authorization: `Basic ${creds}`,
        },
      });

      const initData = await initResponse.json();

      if (!initResponse.ok) {
        throw new Error(initData.detail || `Failed to initialize graph: ${initResponse.statusText}`);
      }

      setStatusMessage(`✅ Graph "${graphName}" created and initialized successfully! You can now close this dialog.`);
      setStatusType("success");
      
      // Add the new graph to the available graphs list
      const newGraph = graphName;
      setAvailableGraphs(prev => {
        if (!prev.includes(newGraph)) {
          const updated = [...prev, newGraph];
          // Update localStorage as well
          const store = JSON.parse(localStorage.getItem("site") || "{}");
          store.graphs = updated;
          localStorage.setItem("site", JSON.stringify(store));
          return updated;
        }
        return prev;
      });
      
      // Set the newly created graph as selected for ingestion
      setIngestGraphName(graphName);
      setRefreshGraphName(graphName);
      setGraphName("");
    } catch (error: any) {
      console.error("Error creating graph:", error);
      setStatusMessage(`❌ Error: ${error.message}`);
      setStatusType("error");
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="h-[100vh] w-full bg-white dark:bg-background p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-10">
          <Button
            variant="outline"
            onClick={() => navigate("/chat")}
            className="mb-4 dark:border-[#3D3D3D]"
          >
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to Chat
          </Button>
          <h1 className="text-2xl font-bold mb-2 text-black dark:text-white">
            Knowledge Graph Setup
          </h1>
          <p className="text-sm text-gray-600 dark:text-[#D9D9D9]">
            Configure and manage your knowledge graphs
          </p>
        </div>

        {/* Three cards displayed horizontally */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          
          {/* Section 1: Add New Knowledge Graph */}
          <div className="border border-gray-300 dark:border-[#3D3D3D] rounded-lg p-6 bg-white dark:bg-shadeA flex flex-col h-full">
            <div className="mb-4">
              <div className="w-12 h-12 rounded-full bg-tigerOrange/10 flex items-center justify-center mb-4">
                <Database className="h-6 w-6 text-tigerOrange" />
              </div>
              <h2 className="text-lg font-semibold mb-2 text-black dark:text-white">
                Add New Knowledge Graph
              </h2>
              <p className="text-sm text-gray-600 dark:text-[#D9D9D9] mb-4">
                Create a new knowledge graph for your data
              </p>
            </div>
            <div className="mt-auto pt-4 border-t border-gray-300 dark:border-[#3D3D3D]">
              <Button 
                className="gradient w-full text-white"
                onClick={() => setCreateGraphOpen(true)}
              >
                <Database className="h-4 w-4 mr-2" />
                Create Graph
              </Button>
            </div>
          </div>

          {/* Section 2: Data Ingest for a KG */}
          <div className="border border-gray-300 dark:border-[#3D3D3D] rounded-lg p-6 bg-white dark:bg-shadeA flex flex-col h-full">
            <div className="mb-4">
              <div className="w-12 h-12 rounded-full bg-tigerOrange/10 flex items-center justify-center mb-4">
                <Upload className="h-6 w-6 text-tigerOrange" />
              </div>
              <h2 className="text-lg font-semibold mb-2 text-black dark:text-white">
                Data Ingest for a KG
              </h2>
              <p className="text-sm text-gray-600 dark:text-[#D9D9D9] mb-4">
                Upload and process data into your knowledge graph
              </p>
            </div>
            <div className="mt-auto pt-4 border-t border-gray-300 dark:border-[#3D3D3D]">
              <Button 
                className="gradient w-full text-white"
                onClick={() => setIngestOpen(true)}
              >
                <Upload className="h-4 w-4 mr-2" />
                Ingest Data
              </Button>
            </div>
          </div>

          {/* Section 3: Refresh Knowledge Graph */}
          <div className="border border-gray-300 dark:border-[#3D3D3D] rounded-lg p-6 bg-white dark:bg-shadeA flex flex-col h-full">
            <div className="mb-4">
              <div className="w-12 h-12 rounded-full bg-tigerOrange/10 flex items-center justify-center mb-4">
                <RefreshCw className="h-6 w-6 text-tigerOrange" />
              </div>
              <h2 className="text-lg font-semibold mb-2 text-black dark:text-white">
                Refresh Knowledge Graph
              </h2>
              <p className="text-sm text-gray-600 dark:text-[#D9D9D9] mb-4">
                Rebuild and refresh your knowledge graph
              </p>
            </div>
            <div className="mt-auto pt-4 border-t border-gray-300 dark:border-[#3D3D3D]">
              <Button 
                className="gradient w-full text-white"
                onClick={() => setRefreshOpen(true)}
              >
                <RefreshCw className="h-4 w-4 mr-2" />
                Refresh Graph
              </Button>
            </div>
          </div>

        </div>

        {/* Create Graph Dialog */}
        <Dialog open={createGraphOpen} onOpenChange={setCreateGraphOpen}>
          <DialogContent className="sm:max-w-[500px] bg-white dark:bg-background border-gray-300 dark:border-[#3D3D3D]">
            <DialogHeader>
              <DialogTitle className="text-black dark:text-white">Create New Knowledge Graph</DialogTitle>
              <DialogDescription className="text-gray-600 dark:text-[#D9D9D9]">
                Enter a name for your new knowledge graph. This will create the graph and initialize the GraphRAG schema.
              </DialogDescription>
            </DialogHeader>
            
            <div className="py-4">
              <div className="mb-4">
                <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                  Graph Name
                </label>
                <Input
                  placeholder="e.g., MyKnowledgeGraph"
                  value={graphName}
                  onChange={(e) => setGraphName(e.target.value)}
                  disabled={isCreating}
                  className="dark:border-[#3D3D3D] dark:bg-shadeA"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !isCreating) {
                      handleCreateGraph();
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
                    setCreateGraphOpen(false);
                    setGraphName("");
                    setStatusMessage("");
                    setStatusType("");
                    // No need to reload - graph list updates dynamically!
                  }}
                >
                  Done
                </Button>
              ) : (
                <>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setCreateGraphOpen(false);
                      setGraphName("");
                      setStatusMessage("");
                      setStatusType("");
                    }}
                    disabled={isCreating}
                    className="dark:border-[#3D3D3D]"
                  >
                    Cancel
                  </Button>
                  <Button
                    onClick={handleCreateGraph}
                    disabled={isCreating || !graphName.trim()}
                    className="gradient text-white"
                  >
                    {isCreating ? (
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

        {/* Data Ingest Dialog */}
        <Dialog open={ingestOpen} onOpenChange={setIngestOpen}>
          <DialogContent className="sm:max-w-[700px] bg-white dark:bg-background border-gray-300 dark:border-[#3D3D3D] max-h-[80vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle className="text-black dark:text-white">Data Ingest for Knowledge Graph</DialogTitle>
              <DialogDescription className="text-gray-600 dark:text-[#D9D9D9]">
                Upload files locally, download from cloud storage, or configure S3 Bedrock for data ingestion
              </DialogDescription>
            </DialogHeader>

            {/* Graph Name Selection */}
            <div className="mb-4">
              <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                Target Graph Name
              </label>
              <Select value={ingestGraphName} onValueChange={setIngestGraphName}>
                <SelectTrigger className="dark:border-[#3D3D3D] dark:bg-shadeA">
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
              {ingestGraphName && (
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Files will be uploaded to: uploads/{ingestGraphName}/
                </p>
              )}
            </div>

            <Tabs defaultValue="upload" className="w-full">
              <TabsList className="grid w-full grid-cols-3">
                <TabsTrigger value="upload">
                  <FolderUp className="h-4 w-4 mr-2" />
                  Upload Data
                </TabsTrigger>
                <TabsTrigger value="cloudDownload">
                  <CloudDownload className="h-4 w-4 mr-2" />
                  Download from Cloud
                </TabsTrigger>
                <TabsTrigger value="s3">
                  <Cloud className="h-4 w-4 mr-2" />
                  S3 Bedrock Configuration
                </TabsTrigger>
              </TabsList>

              {/* Upload Data Tab */}
              <TabsContent value="upload" className="space-y-4">
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                      Select Files
                    </label>
                    <Input
                      type="file"
                      multiple
                      onChange={(e) => setSelectedFiles(e.target.files)}
                      disabled={isUploading}
                      className="dark:border-[#3D3D3D] dark:bg-shadeA"
                    />
                  </div>

                  <div className="flex gap-2">
                    <Button
                      onClick={handleUploadFiles}
                      disabled={isUploading || !selectedFiles}
                      className="gradient text-white"
                    >
                      {isUploading ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          Uploading...
                        </>
                      ) : (
                        <>
                          <Upload className="h-4 w-4 mr-2" />
                          Upload Files
                        </>
                      )}
                    </Button>

                    {uploadedFiles.length > 0 && (
                      <Button
                        onClick={handleDeleteAllFiles}
                        variant="outline"
                        className="dark:border-[#3D3D3D]"
                      >
                        <Trash2 className="h-4 w-4 mr-2" />
                        Delete All
                      </Button>
                    )}
                  </div>

                  {uploadMessage && (
                    <div className="p-3 rounded-lg text-sm bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300">
                      {uploadMessage}
                    </div>
                  )}

                  {/* Ingest Data Section */}
                  {uploadedFiles.length > 0 && (
                    <div className="border-t border-gray-300 dark:border-[#3D3D3D] pt-4 mt-4">
                      <h3 className="text-sm font-medium mb-2 text-black dark:text-white">
                        Ingest Data into Knowledge Graph
                      </h3>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
                        Process uploaded files and add them to the knowledge graph
                      </p>
                      <Button
                        onClick={() => handleIngestData("uploaded")}
                        disabled={isIngesting}
                        className="gradient text-white w-full"
                      >
                        {isIngesting ? (
                          <>
                            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                            Ingesting...
                          </>
                        ) : (
                          <>
                            <Database className="h-4 w-4 mr-2" />
                            Ingest Data into {ingestGraphName}
                          </>
                        )}
                      </Button>
                      {ingestMessage && (
                        <div className={`p-3 rounded-lg text-sm mt-3 ${
                          ingestMessage.includes("✅")
                            ? "bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300"
                            : ingestMessage.includes("❌")
                            ? "bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300"
                            : "bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300"
                        }`}>
                          {ingestMessage}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Uploaded Files List */}
                  {uploadedFiles.length > 0 && (
                    <div className="border border-gray-300 dark:border-[#3D3D3D] rounded-lg p-4">
                      <h3 className="text-sm font-medium mb-3 text-black dark:text-white">
                        Uploaded Files ({uploadedFiles.length})
                      </h3>
                      <div className="space-y-2 max-h-48 overflow-y-auto">
                        {uploadedFiles.map((file, index) => (
                          <div
                            key={index}
                            className="flex items-center justify-between p-2 bg-gray-50 dark:bg-shadeA rounded"
                          >
                            <span className="text-sm text-black dark:text-white truncate flex-1">
                              {file.filename}
                            </span>
                            <Button
                              onClick={() => handleDeleteFile(file.filename)}
                              variant="outline"
                              size="sm"
                              className="ml-2 dark:border-[#3D3D3D]"
                            >
                              <Trash2 className="h-3 w-3" />
                            </Button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </TabsContent>

              {/* Download from Cloud Storage Tab */}
              <TabsContent value="cloudDownload" className="space-y-4">
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                      Cloud Storage Provider
                    </label>
                    <Select value={cloudProvider} onValueChange={(value: "s3" | "gcs" | "azure") => setCloudProvider(value)}>
                      <SelectTrigger className="dark:border-[#3D3D3D] dark:bg-shadeA">
                        <SelectValue placeholder="Select cloud provider" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="s3">Amazon S3</SelectItem>
                        <SelectItem value="gcs">Google Cloud Storage</SelectItem>
                        <SelectItem value="azure">Azure Blob Storage</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  {/* Amazon S3 */}
                  {cloudProvider === "s3" && (
                    <>
                      <div>
                        <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                          AWS Access Key
                        </label>
                        <Input
                          type="text"
                          value={cloudAccessKey}
                          onChange={(e) => setCloudAccessKey(e.target.value)}
                          placeholder="Enter AWS access key"
                          className="dark:border-[#3D3D3D] dark:bg-shadeA"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                          AWS Secret Key
                        </label>
                        <Input
                          type="password"
                          value={cloudSecretKey}
                          onChange={(e) => setCloudSecretKey(e.target.value)}
                          placeholder="Enter AWS secret key"
                          className="dark:border-[#3D3D3D] dark:bg-shadeA"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                          S3 Bucket Name
                        </label>
                        <Input
                          type="text"
                          value={cloudBucket}
                          onChange={(e) => setCloudBucket(e.target.value)}
                          placeholder="my-bucket-name"
                          className="dark:border-[#3D3D3D] dark:bg-shadeA"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                          Region
                        </label>
                        <Input
                          type="text"
                          value={cloudRegion}
                          onChange={(e) => setCloudRegion(e.target.value)}
                          placeholder="us-east-1"
                          className="dark:border-[#3D3D3D] dark:bg-shadeA"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                          Prefix/Path (Optional)
                        </label>
                        <Input
                          type="text"
                          value={cloudPrefix}
                          onChange={(e) => setCloudPrefix(e.target.value)}
                          placeholder="folder/subfolder/"
                          className="dark:border-[#3D3D3D] dark:bg-shadeA"
                        />
                      </div>
                    </>
                  )}

                  {/* Google Cloud Storage */}
                  {cloudProvider === "gcs" && (
                    <>
                      <div>
                        <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                          Project ID
                        </label>
                        <Input
                          type="text"
                          value={gcsProjectId}
                          onChange={(e) => setGcsProjectId(e.target.value)}
                          placeholder="my-project-id"
                          className="dark:border-[#3D3D3D] dark:bg-shadeA"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                          Service Account JSON
                        </label>
                        <textarea
                          value={gcsCredentials}
                          onChange={(e) => setGcsCredentials(e.target.value)}
                          placeholder='{"type": "service_account", ...}'
                          rows={4}
                          className="w-full p-2 rounded border dark:border-[#3D3D3D] dark:bg-shadeA text-sm"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                          Bucket Name
                        </label>
                        <Input
                          type="text"
                          value={cloudBucket}
                          onChange={(e) => setCloudBucket(e.target.value)}
                          placeholder="my-gcs-bucket"
                          className="dark:border-[#3D3D3D] dark:bg-shadeA"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                          Prefix/Path (Optional)
                        </label>
                        <Input
                          type="text"
                          value={cloudPrefix}
                          onChange={(e) => setCloudPrefix(e.target.value)}
                          placeholder="folder/subfolder/"
                          className="dark:border-[#3D3D3D] dark:bg-shadeA"
                        />
                      </div>
                    </>
                  )}

                  {/* Azure Blob Storage */}
                  {cloudProvider === "azure" && (
                    <>
                      <div>
                        <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                          Storage Account Name
                        </label>
                        <Input
                          type="text"
                          value={azureAccountName}
                          onChange={(e) => setAzureAccountName(e.target.value)}
                          placeholder="mystorageaccount"
                          className="dark:border-[#3D3D3D] dark:bg-shadeA"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                          Account Key
                        </label>
                        <Input
                          type="password"
                          value={azureAccountKey}
                          onChange={(e) => setAzureAccountKey(e.target.value)}
                          placeholder="Enter account key"
                          className="dark:border-[#3D3D3D] dark:bg-shadeA"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                          Container Name
                        </label>
                        <Input
                          type="text"
                          value={azureContainer}
                          onChange={(e) => setAzureContainer(e.target.value)}
                          placeholder="my-container"
                          className="dark:border-[#3D3D3D] dark:bg-shadeA"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                          Prefix/Path (Optional)
                        </label>
                        <Input
                          type="text"
                          value={cloudPrefix}
                          onChange={(e) => setCloudPrefix(e.target.value)}
                          placeholder="folder/subfolder/"
                          className="dark:border-[#3D3D3D] dark:bg-shadeA"
                        />
                      </div>
                    </>
                  )}

                  <div className="pt-4 border-t border-gray-300 dark:border-[#3D3D3D]">
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
                      Files will be downloaded to: downloaded_files_cloud/{ingestGraphName}/
                    </p>
                    <Button 
                      onClick={handleCloudDownload}
                      disabled={isDownloading}
                      className="gradient text-white w-full"
                    >
                      {isDownloading ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          Downloading...
                        </>
                      ) : (
                        <>
                          <CloudDownload className="h-4 w-4 mr-2" />
                          Download Files from {cloudProvider === "s3" ? "S3" : cloudProvider === "gcs" ? "GCS" : "Azure"}
                        </>
                      )}
                    </Button>
                  </div>

                  {downloadMessage && (
                    <div className={`p-3 rounded-lg text-sm mt-3 ${
                      downloadMessage.includes("✅")
                        ? "bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300"
                        : downloadMessage.includes("❌")
                        ? "bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300"
                        : "bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300"
                    }`}>
                      {downloadMessage}
                    </div>
                  )}

                  {/* Downloaded Files List */}
                  {downloadedFiles.length > 0 && (
                    <div className="mt-4 border-t border-gray-300 dark:border-[#3D3D3D] pt-4">
                      <div className="flex justify-between items-center mb-2">
                        <h4 className="text-sm font-medium text-black dark:text-white">
                          Downloaded Files ({downloadedFiles.length})
                        </h4>
                        <Button
                          onClick={handleDeleteAllDownloadedFiles}
                          variant="outline"
                          size="sm"
                          className="dark:border-[#3D3D3D]"
                        >
                          <Trash2 className="h-3 w-3 mr-1" />
                          Delete All
                        </Button>
                      </div>
                      <ul className="space-y-2 max-h-40 overflow-y-auto">
                        {downloadedFiles.map((file, index) => (
                          <li
                            key={index}
                            className="flex justify-between items-center p-2 bg-gray-50 dark:bg-shadeA rounded text-sm"
                          >
                            <span className="text-black dark:text-white truncate flex-1">
                              {file.name}
                            </span>
                            <Button
                              onClick={() => handleDeleteDownloadedFile(file.name)}
                              variant="ghost"
                              size="sm"
                              className="ml-2 text-red-500 hover:text-red-700 dark:hover:text-red-400"
                            >
                              <Trash2 className="h-3 w-3" />
                            </Button>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Ingest Downloaded Data Section */}
                  {downloadedFiles.length > 0 && (
                    <div className="border-t border-gray-300 dark:border-[#3D3D3D] pt-4 mt-4">
                      <h3 className="text-sm font-medium mb-2 text-black dark:text-white">
                        Ingest Downloaded Data into Knowledge Graph
                      </h3>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
                        Process downloaded files and add them to the knowledge graph
                      </p>
                      <Button
                        onClick={() => handleIngestData("downloaded")}
                        disabled={isIngesting}
                        className="gradient text-white w-full"
                      >
                        {isIngesting ? (
                          <>
                            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                            Ingesting...
                          </>
                        ) : (
                          <>
                            <Database className="h-4 w-4 mr-2" />
                            Ingest Downloaded Data into {ingestGraphName}
                          </>
                        )}
                      </Button>
                      {ingestMessage && (
                        <div className={`p-3 rounded-lg text-sm mt-3 ${
                          ingestMessage.includes("✅")
                            ? "bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300"
                            : ingestMessage.includes("❌")
                            ? "bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300"
                            : "bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300"
                        }`}>
                          {ingestMessage}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </TabsContent>

              {/* S3 Bedrock Configuration Tab */}
              <TabsContent value="s3" className="space-y-4">
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                      File Format
                    </label>
                    <Select value={fileFormat} onValueChange={(value: "json" | "multi") => setFileFormat(value)}>
                      <SelectTrigger className="dark:border-[#3D3D3D] dark:bg-shadeA">
                        <SelectValue placeholder="Select file format" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="json">JSON</SelectItem>
                        <SelectItem value="multi">Multi</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  {/* Common fields */}
                  <div>
                    <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                      AWS Access Key
                    </label>
                    <Input
                      type="text"
                      value={awsAccessKey}
                      onChange={(e) => setAwsAccessKey(e.target.value)}
                      placeholder="Enter AWS access key"
                      className="dark:border-[#3D3D3D] dark:bg-shadeA"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                      AWS Secret Key
                    </label>
                    <Input
                      type="password"
                      value={awsSecretKey}
                      onChange={(e) => setAwsSecretKey(e.target.value)}
                      placeholder="Enter AWS secret key"
                      className="dark:border-[#3D3D3D] dark:bg-shadeA"
                    />
                  </div>

                  {/* Conditional fields based on file format */}
                  {fileFormat === "json" ? (
                    <div>
                      <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                        Data Path
                      </label>
                      <Input
                        type="text"
                        value={dataPath}
                        onChange={(e) => setDataPath(e.target.value)}
                        placeholder="s3://bucket-name/path/to/data"
                        className="dark:border-[#3D3D3D] dark:bg-shadeA"
                      />
                    </div>
                  ) : (
                    <>
                      <div>
                        <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                          Input Bucket
                        </label>
                        <Input
                          type="text"
                          value={inputBucket}
                          onChange={(e) => setInputBucket(e.target.value)}
                          placeholder="Enter input bucket name"
                          className="dark:border-[#3D3D3D] dark:bg-shadeA"
                        />
                      </div>

                      <div>
                        <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                          Output Bucket
                        </label>
                        <Input
                          type="text"
                          value={outputBucket}
                          onChange={(e) => setOutputBucket(e.target.value)}
                          placeholder="Enter output bucket name"
                          className="dark:border-[#3D3D3D] dark:bg-shadeA"
                        />
                      </div>

                      <div>
                        <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                          Region Name
                        </label>
                        <Input
                          type="text"
                          value={regionName}
                          onChange={(e) => setRegionName(e.target.value)}
                          placeholder="e.g., us-east-1"
                          className="dark:border-[#3D3D3D] dark:bg-shadeA"
                        />
                      </div>
                    </>
                  )}
                </div>
              </TabsContent>
            </Tabs>

            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setIngestOpen(false);
                  setUploadMessage("");
                }}
                className="dark:border-[#3D3D3D]"
              >
                Close
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* Refresh Graph Dialog */}
        <Dialog open={refreshOpen} onOpenChange={setRefreshOpen}>
          <DialogContent className="sm:max-w-[500px] bg-white dark:bg-background border-gray-300 dark:border-[#3D3D3D]">
            <DialogHeader>
              <DialogTitle className="text-black dark:text-white">Refresh Knowledge Graph</DialogTitle>
              <DialogDescription className="text-gray-600 dark:text-[#D9D9D9]">
                Rebuild the community structure of your knowledge graph
              </DialogDescription>
            </DialogHeader>

            <div className="py-4 space-y-4">
              <div>
                <label className="block text-sm font-medium mb-2 text-black dark:text-white">
                  Select Graph to Refresh
                </label>
                <Select value={refreshGraphName} onValueChange={setRefreshGraphName}>
                  <SelectTrigger className="dark:border-[#3D3D3D] dark:bg-shadeA">
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
                  This operation will rebuild community that will interrupt related queries. 
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
                onClick={() => {
                  setRefreshOpen(false);
                  setRefreshMessage("");
                }}
                disabled={isRefreshing}
                className="dark:border-[#3D3D3D]"
              >
                Cancel
              </Button>
              <Button
                onClick={handleRefreshGraph}
                disabled={isRefreshing || !refreshGraphName}
                className="gradient text-white"
              >
                {isRefreshing ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Refreshing...
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
    </div>
  );
};

export default Setup;

