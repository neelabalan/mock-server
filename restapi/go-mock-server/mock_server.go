package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"time"
)

type ApiFormat struct {
	Url      string         `json:"url"`
	Method   string         `json:"method"`
	Response ResponseFormat `json:"response"`
	Delay    int            `json:"delay"`
}

type ResponseFormat struct {
	Status  int                    `json:"status"`
	Headers map[string]interface{} `json:"headers"`
	Body    map[string]interface{} `json:"body"`
}

func check(e error) {
	if e != nil {
		slog.Error("Error occurred", "error", e)
		panic(e)
	}
}

func main() {
	debug := flag.Bool("debug", false, "enable debug logging")
	mock_data := flag.String("mock-data", "../data/sample.json", "config for creating mock server")
	port := flag.Int("port", 8080, "port exposed")
	flag.Parse()

	// Set log level based on debug flag
	if *debug {
		slog.SetLogLoggerLevel(slog.LevelDebug)
	}

	file, err := os.ReadFile(*mock_data)
	check(err)
	apis := []ApiFormat{}
	json.Unmarshal(file, &apis)
	for _, api := range apis {
		api := api // capture loop var for closure
		http.HandleFunc(api.Method+" "+api.Url, func(w http.ResponseWriter, r *http.Request) {
			// set response headers
			for key, val := range api.Response.Headers {
				w.Header().Set(key, fmt.Sprint(val))
			}
			w.WriteHeader(api.Response.Status)
			slog.Debug("API request handled", "method", api.Method, "url", api.Url, "status", api.Response.Status)
			if api.Response.Body != nil {
				json.NewEncoder(w).Encode(api.Response.Body)
			}
			if api.Delay > 0 {
				time.Sleep(time.Duration(api.Delay) * time.Millisecond)
			}
		})
		slog.Info("Registered endpoint", "method", api.Method, "url", api.Url)
	}
	slog.Info("Starting server", "port", port)
	http.ListenAndServe(fmt.Sprintf(":%s", port), nil)
}
