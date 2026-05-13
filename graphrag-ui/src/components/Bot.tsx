import "react-chatbot-kit/build/main.css";
import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import Chatbot from "react-chatbot-kit";
import ActionProvider from "../actions/ActionProvider.js";
import config from "../actions/config.js";
import MessageParser from "../actions/MessageParser.js";
import { MdKeyboardArrowDown } from "react-icons/md";
import { SelectedGraphContext, RagPatternContext } from './Contexts.js';

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
import { readSiteSession, refreshSiteSession } from "@/lib/siteSession";

const Bot = ({ layout, getConversationId }: { layout?: string | undefined, getConversationId?:any }) => {
  const [store, setStore] = useState<any>();
  const [currentDate, setCurrentDate] = useState('');
  const [selectedGraph, setSelectedGraph] = useState(sessionStorage.getItem("selectedGraph") || '');
  const [ragPattern, setRagPattern] = useState(sessionStorage.getItem("ragPattern") || '');
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const syncStore = async () => {
      try {
        const site = await refreshSiteSession();
        setStore(site);
        setSelectedGraph(sessionStorage.getItem("selectedGraph") || "");
      } catch {
        const site = readSiteSession();
        setStore(site);
        setSelectedGraph(sessionStorage.getItem("selectedGraph") || "");
      }
    };

    void syncStore();

    // Set default ragPattern if no value in sessionStorage
    if (!sessionStorage.getItem("ragPattern")) {
      setRagPattern("Auto Router");
      sessionStorage.setItem("ragPattern", "Auto Router");
    }

    const date = new Date();
    const options: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' };
    const formattedDate = date.toLocaleDateString('en-US', options);
    setCurrentDate(formattedDate);

    // Update graph list when window gets focus (when navigating back from Setup)
    const handleFocus = () => {
      void syncStore();
    };

    window.addEventListener('focus', handleFocus);

    // Cleanup
    return () => {
      window.removeEventListener('focus', handleFocus);
    };
  }, []);

  // Reload graph list when navigating back to chat (location change)
  useEffect(() => {
    const syncStore = async () => {
      try {
        const site = await refreshSiteSession();
        setStore(site);
      } catch {
        setStore(readSiteSession());
      }
      setSelectedGraph(sessionStorage.getItem("selectedGraph") || "");
    };
    void syncStore();
  }, [location]);

  const handleSelect = (value) => {
    setSelectedGraph(value);
    sessionStorage.setItem("selectedGraph", value);
    window.dispatchEvent(new Event("graphrag:selectedGraph"));
    navigate("/chat");
    //window.location.reload();
  };

  const handleSelectRag = (value) => {
    setRagPattern(value);
    sessionStorage.setItem("ragPattern", value);
    navigate("/chat");
    //window.location.reload();
  };

  return (
    <div className={layout}>
      {/* {layout === "fp" && ( */}
        <div className="border-b border-gray-300 dark:border-[#3D3D3D] h-[70px] flex items-center bg-white dark:bg-background z-50 rounded-tr-lg px-5">
          <div className="text-sm mr-8">{currentDate}</div>

          <div className="flex gap-4 mr-auto">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  className="!h-[48px] !outline-b !outline-gray-300 dark:!outline-[#3D3D3D] h-[70px] flex justify-end items-center bg-white dark:bg-background z-50 rounded-tr-lg"
                >
                  <img src="/graph-icon.svg" alt="" className="mr-2" />
                  {ragPattern} <MdKeyboardArrowDown className="text-2xl" />
                </Button>
              </DropdownMenuTrigger>

              <DropdownMenuContent className="w-56">
                <DropdownMenuLabel>Select a GraphRAG Pattern</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                  {["Auto Router", "Similarity Search", "Contextual Search", "Hybrid Search", "Community Search"].map((f, i) => (
                    <DropdownMenuItem key={i} onSelect={() => handleSelectRag(f)}>
                      {/* <User className="mr-2 h-4 w-4" /> */}
                      <span>{f}</span>
                      {/* <DropdownMenuShortcut>⇧⌘P</DropdownMenuShortcut> */}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  className="!h-[48px] !outline-b !outline-gray-300 dark:!outline-[#3D3D3D] h-[70px] flex justify-end items-center bg-white dark:bg-background z-50 rounded-tr-lg"
                >
                  <img src="/graph-icon.svg" alt="" className="mr-2" />
                  {selectedGraph || <span className="text-gray-400 italic">No Knowledge Graph</span>} <MdKeyboardArrowDown className="text-2xl" />
                </Button>
              </DropdownMenuTrigger>

            <DropdownMenuContent className="w-56">
              <DropdownMenuLabel>Select a KnowledgeGraph</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuGroup>
                {store?.graphs?.length > 0 ? (
                  store.graphs.map((f, i) => (
                    <DropdownMenuItem key={i} onSelect={() => handleSelect(f)}>
                      <span>{f}</span>
                    </DropdownMenuItem>
                  ))
                ) : (
                  <DropdownMenuItem disabled>
                    <span className="text-gray-400 italic text-sm">
                      Please create a Knowledge Graph in Setup first
                    </span>
                  </DropdownMenuItem>
                )}
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
          </div>
        </div>
      
      <SelectedGraphContext.Provider value={selectedGraph}>
        <RagPatternContext.Provider value={ragPattern}>
          <Chatbot
            // eslint-disable-next-line
            // @ts-ignore
            config={config}
            fullPage={layout}
            getConversationId={getConversationId}
            messageParser={MessageParser}
            actionProvider={ActionProvider}
          />
        </RagPatternContext.Provider>
      </SelectedGraphContext.Provider>
    </div>
  );
};

export default Bot;
