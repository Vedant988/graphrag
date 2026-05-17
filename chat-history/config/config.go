package config

import (
	"encoding/json"
	"os"
	"strings"
)

type LLMConfig struct {
	ModelName string `json:"model_name"`
}

type ChatDbConfig struct {
	Port                    string   `json:"apiPort"`
	DbPath                  string   `json:"dbPath"`
	DbLogPath               string   `json:"dbLogPath"`
	LogPath                 string   `json:"logPath"`
	ConversationAccessRoles []string `json:"conversationAccessRoles"`
}

type TgDbConfig struct {
	Hostname string `json:"hostname"`
	Username string `json:"username"`
	Password string `json:"password"`
	GsPort   string `json:"gsPort"`
	// GetToken string `json:"getToken"`
	// DefaultTimeout       string `json:"default_timeout"`
	// DefaultMemThreshold string `json:"default_mem_threshold"`
	// DefaultThreadLimit  string `json:"default_thread_limit"`
}

type Config struct {
	TgDbConfig   TgDbConfig   `json:"db_config"`
	ChatDbConfig ChatDbConfig `json:"chat_config"`
	// LLMConfig LLMConfig `json:"llm_config"`
}

func LoadConfig(paths map[string]string) (Config, error) {
	config := Config{
		ChatDbConfig: ChatDbConfig{
			Port:      "8002",
			DbPath:    "chats.db",
			DbLogPath: "db.log",
			LogPath:   "requestLogs.jsonl",
		},
	}

	if configPath, ok := paths["tgconfig"]; ok && strings.TrimSpace(configPath) != "" {
		rawConfig := strings.TrimSpace(configPath)
		var b []byte
		if strings.HasPrefix(rawConfig, "{") {
			b = []byte(rawConfig)
		} else {
			fileBytes, err := os.ReadFile(rawConfig)
			if err != nil {
				return Config{}, err
			}
			b = fileBytes
		}
		if err := json.Unmarshal(b, &config); err != nil {
			return Config{}, err
		}
	}

	applyEnvOverrides(&config)
	return config, nil
}

func applyEnvOverrides(config *Config) {
	if value := strings.TrimSpace(os.Getenv("TIGERGRAPH_HOSTNAME")); value != "" {
		config.TgDbConfig.Hostname = value
	}
	if value := strings.TrimSpace(os.Getenv("TIGERGRAPH_USERNAME")); value != "" {
		config.TgDbConfig.Username = value
	}
	if value := strings.TrimSpace(os.Getenv("TIGERGRAPH_PASSWORD")); value != "" {
		config.TgDbConfig.Password = value
	}
	if value := strings.TrimSpace(os.Getenv("TIGERGRAPH_GS_PORT")); value != "" {
		config.TgDbConfig.GsPort = value
	}
	if value := strings.TrimSpace(os.Getenv("PORT")); value != "" {
		config.ChatDbConfig.Port = value
	}
	if value := strings.TrimSpace(os.Getenv("CHAT_DB_PATH")); value != "" {
		config.ChatDbConfig.DbPath = value
	}
	if value := strings.TrimSpace(os.Getenv("CHAT_DB_LOG_PATH")); value != "" {
		config.ChatDbConfig.DbLogPath = value
	}
	if value := strings.TrimSpace(os.Getenv("CHAT_LOG_PATH")); value != "" {
		config.ChatDbConfig.LogPath = value
	}
}
