#pragma once

#include "CoreMinimal.h"
#include "ScopedTransaction.h"

/**
 * Standard mutation convention: construct only after validation/preview, call
 * Modify() on every changed UObject, and record every path in FCotSOperationResult.
 * A dry run never opens an editor transaction.
 */
class FCotSEditorMutationScope
{
public:
    FCotSEditorMutationScope(const FText& Description, UObject* PrimaryObject, bool bDryRun)
        : Transaction(TEXT("CotSDeveloperTools"), Description, PrimaryObject, !bDryRun)
    {
    }

private:
    FScopedTransaction Transaction;
};
