#pragma once
#include "Domains/CotSDomainToolset.h"
class ICotSInspectionDomain : public ICotSDomainToolset { public: virtual FString GetDomainName() const override { return TEXT("Inspection"); } };
