#pragma once

#include "CoreMinimal.h"

/** Marker interface for a future CotS domain toolset. Domain implementations must depend on Core, not each other. */
class ICotSDomainToolset
{
public:
    virtual ~ICotSDomainToolset() = default;
    virtual FString GetDomainName() const = 0;
};
