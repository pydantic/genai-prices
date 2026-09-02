package main

import (
	"encoding/json"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
)

type declaration struct {
	Path string `json:"path"`
	Kind string `json:"kind"`
	Name string `json:"name"`
}

func main() {
	declarations := make([]declaration, 0)
	for _, path := range os.Args[1:] {
		if path == "--" {
			continue
		}
		file, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
		if err != nil {
			fail(err)
		}
		if file.Name.Name != "genai_prices" {
			continue
		}
		for _, node := range file.Decls {
			switch node := node.(type) {
			case *ast.FuncDecl:
				if node.Recv == nil {
					declarations = append(declarations, declaration{Path: path, Kind: "func", Name: node.Name.Name})
				}
			case *ast.GenDecl:
				for _, spec := range node.Specs {
					switch spec := spec.(type) {
					case *ast.TypeSpec:
						declarations = append(declarations, declaration{Path: path, Kind: "type", Name: spec.Name.Name})
					case *ast.ValueSpec:
						for _, name := range spec.Names {
							declarations = append(
								declarations,
								declaration{Path: path, Kind: node.Tok.String(), Name: name.Name},
							)
						}
					}
				}
			}
		}
	}
	if err := json.NewEncoder(os.Stdout).Encode(declarations); err != nil {
		fail(err)
	}
}

func fail(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
