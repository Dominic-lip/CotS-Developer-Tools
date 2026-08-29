#pragma once
#include "Domains/CotSDomainToolset.h"
class ICotSMetaHumanDomain : public ICotSDomainToolset { public: virtual FString GetDomainName() const override { return TEXT("MetaHuman"); } };
