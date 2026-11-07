# Ninja Kaizen Macro v3

Extract to its own folder and launch Start.cmd. The first launch needs Python 3 and an internet connection for setup.

## Set up a mission

1. Choose Grade A, B, or C. Enter the mission name, the full page counter as shown in the game, and the row number (1 top, 2 middle, 3 bottom).
2. In Ninja Kaizen, open that grade and page manually. Verify the name and row, move your cursor away from the list, and press F7 while the game is in focus. The macro saves visual references for that page and row. The name and counter you type are labels for the saved setup.
3. Return to the launcher. Choose 1 for Normal Attack only, or 2 for skills first. Skills mode checks the first seven icons left to right, skips greyed-out slots, and uses Normal Attack if none are available.
4. Choose a run count. Use 1 for a first test or 0 for continuous farming. From the village or your configured mission page, press F8 to start.

After a batch finishes, the launcher returns to mission setup. Press Enter to reuse the saved mission, S to set up a different mission, or Q to quit. You can change combat mode and run count on every launch.

Press Escape to return to mission setup. Switching windows pauses the current batch. Return to the game and press F8 to resume that paused batch with its completed-run count. If the mission is still active, the macro continues from the current game screen. If the game is back at the village before the reward was claimed, it retries that mission. Close the launcher console to quit. F9 finishes the current fight or reward screen and returns to mission setup. Keep Ninja Kaizen fully visible and in focus, with its window position and size fixed while the macro runs. If you are on a page after the configured mission, start from the village so pagination can begin from the first page.

Menu recognition and both combat choices were checked against saved screenshots. Test a full run in the game before using continuous mode.

