# chef_assistant

#=================================================================
# -- Project Chain Steps (Workflow Diagram) --
#=================================================================

#
#       [ 1. Image Upload ]
#                 │
#                 ▼
#       [ 2. image_to_text ] ──(If no ingredients)──► [ END ]
#                 │
#                 ▼ (Ingredients detected)
#       [ 3. rss_recipe_search ]
#                 │
#                 ▼
#     [ 4. filter_search_results ]
#                 │
#                 ▼
#      [ 5. user selects recipe ]
#                 │
#         ┌───────┴───────┐
#         │               │ (Scrape failed / 403 Forbidden)
#         ▼ (Success)     ▼
#    [ 6/A. scrape ]   [ 6/B. generate_final ]
#    [ _recipe_details ] [ _recipe ]
#         │               │
#         └───────┬───────┘
#                 │
#                 ▼
#          [ 7. response ]
#                 │
#                 ▼
#              [ END ]
#
