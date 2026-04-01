# CLAUDE.md — Agent Context Builder                             
                                                                                                                        
  ## What This Project Is                                                                                               
   
  This repo contains **decision-oriented game context** for AI agents that play                                         
  Kamigotchi — a pure on-chain MMORPG on Yominet. It is Layer 2b of the
  documentation pipeline, distilled from the technical GDD at                                                           
  `~/kamigotchi-gdd`.                                                                                                   
                                                                                                                        
  ## Your Role                                                                                                          
                                                                                                                        
  You are building context files that help an AI agent make optimal in-game                                             
  decisions. You are NOT writing player tutorials or technical docs.
                                                                                                                        
  ## Source of Truth                                              
                                                                                                                        
  - **GDD repo (Layer 1)**: `~/kamigotchi-gdd` — mechanics, formulas, catalogs                                          
  - **Game source code**: `https://github.com/Asphodel-OS/kamigotchi`
  - When in doubt, read the GDD mechanic file for the exact formula.                                                    
                                                                                                                        
  ## Writing Rules                                                                                                      
                                                                                                                        
  1. **Decision-first**: every section should answer "what should the agent do?"                                        
  2. **Terse**: no narrative, no flavor text, no "in Kamigotchi, players can..."
  3. **Conditional**: use "if X, then Y" patterns, not prose descriptions                                               
  4. **Quantitative**: include exact thresholds, ratios, and formulas that affect decisions                             
  5. **Referenced**: link to GDD files for deep dives, don't duplicate formulas                                         
  6. **State-aware**: describe what game state the agent should check before acting                                     
  7. README.md is the entry point — it must fit in ~2-3 pages and link to everything                                    
  8. System files go in `systems/`, catalogs in `catalogs/`, strategy guides in `strategies/`                           
  9. Mark any uncertain decision heuristics with `> ⚠️  HEURISTIC:` — needs playtesting                                  
  10. Catalogs are CSV with a comment header explaining key columns and decision relevance
