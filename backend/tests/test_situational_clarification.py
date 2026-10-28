import asyncio
import os
import sys

# Ensure backend app is on sys.path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app import chat as chat_module

async def main():
    print("--- TEST 1: Ambiguous SKU Query ('sales for BS') ---")
    res1 = await chat_module.chat("What is the sales for BS between 1 April and 15 April?", None)
    conv_id = res1["conversation_id"]
    clarif1 = res1.get("clarification")
    print("Answer 1 text:", res1["answer_text"][:120])
    print("Clarification payload:", clarif1)
    assert clarif1 is not None, "Clarification payload must NOT be None when ambiguous!"
    assert clarif1["entity_type"] == "sku"
    assert len(clarif1["options"]) > 0
    print(f"Passed Test 1! Found {len(clarif1['options'])} options for BS.")

    print("\n--- TEST 2: User selects Option 1 ('1. Coffee-Cafe Supreme-200') ---")
    chosen_opt = clarif1["options"][0]
    choice_msg = f"{chosen_opt['id']}. {chosen_opt['label']}"
    print(f"Sending user choice: '{choice_msg}'")
    res2 = await chat_module.chat(choice_msg, conv_id)
    print("Answer 2 text:", res2["answer_text"][:160])
    clarif2 = res2.get("clarification")
    print("Clarification payload after resolution:", clarif2)
    assert clarif2 is None, "Clarification payload must be None after resolution!"
    print("Passed Test 2! Clarification resolved and question bar cleanly unmounted.")

    print("\n--- TEST 3: Ambiguous Customer Query ('sales for Shanthi Sagar') ---")
    res3 = await chat_module.chat("Show sales for Shanthi Sagar in April 2026", None)
    conv_id_cust = res3["conversation_id"]
    clarif3 = res3.get("clarification")
    print("Answer 3 text:", res3["answer_text"][:120])
    print("Clarification payload:", clarif3)
    assert clarif3 is not None, "Clarification payload must NOT be None for multiple customer branches!"
    assert clarif3["entity_type"] == "customer"
    print(f"Passed Test 3! Found {len(clarif3['options'])} branch options for Shanthi Sagar.")

    print("\n--- TEST 4: Non-ambiguous Query ('total coffee sales') ---")
    res4 = await chat_module.chat("total coffee sales from 1 April to 15 April", None)
    clarif4 = res4.get("clarification")
    print("Clarification payload for regular query:", clarif4)
    assert clarif4 is None, "Clarification must be None for non-ambiguous queries (situational only)!"
    print("Passed Test 4! Situational only confirmed.")

    print("\nALL AUTOMATED TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(main())
